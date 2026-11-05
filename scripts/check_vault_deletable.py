"""Confirm recovery points in the demo vault can be deleted (no Vault Lock, no deny policy, no SCP block)."""
from __future__ import annotations

import json
import time
import uuid

from botocore.exceptions import ClientError

from common import Ctx, base_parser, log


def static_checks(ctx: Ctx) -> bool:
    ok = True
    v = ctx.backup.describe_backup_vault(BackupVaultName=ctx.vault)
    if v.get("Locked") or v.get("MinRetentionDays") or v.get("MaxRetentionDays"):
        log.error("FAIL: vault has Vault Lock configured: %s", {k: v.get(k) for k in ("Locked", "MinRetentionDays", "MaxRetentionDays")})
        ok = False
    if v.get("VaultType", "BACKUP_VAULT") != "BACKUP_VAULT":
        log.error("FAIL: vault type is %s (must be a standard vault)", v.get("VaultType"))
        ok = False
    try:
        pol = json.loads(ctx.backup.get_backup_vault_access_policy(BackupVaultName=ctx.vault)["Policy"])
        for st in pol.get("Statement", []):
            acts = st.get("Action", [])
            acts = [acts] if isinstance(acts, str) else acts
            if st.get("Effect") == "Deny" and any(a in ("*", "backup:*", "backup:DeleteRecoveryPoint") for a in acts):
                log.error("FAIL: vault access policy denies DeleteRecoveryPoint")
                ok = False
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("ResourceNotFoundException", "ResourceNotFound"):
            raise
    # IAM simulation (does NOT evaluate SCPs, so --deep is the authoritative check).
    try:
        sts = ctx.session.client("sts").get_caller_identity()
        arn = sts["Arn"]
        if ":assumed-role/" in arn:
            parts = arn.split(":")
            role = parts[5].split("/")[1]
            arn = f"arn:aws:iam::{sts['Account']}:role/{role}"
        sim = ctx.session.client("iam").simulate_principal_policy(
            PolicySourceArn=arn, ActionNames=["backup:DeleteRecoveryPoint"])
        dec = sim["EvaluationResults"][0]["EvalDecision"]
        log.info("IAM simulation for backup:DeleteRecoveryPoint: %s (SCPs not evaluated)", dec)
        ok = ok and dec == "allowed"
    except ClientError as e:
        log.warning("IAM simulation skipped: %s", e.response["Error"]["Code"])
    return ok


def deep_check(ctx: Ctx) -> bool:
    """Create a tiny tagged bucket, back it up, delete the recovery point, clean up."""
    name = f"s3demo-{ctx.demo_id}-chk-{uuid.uuid4().hex[:6]}"
    s3, region = ctx.s3, ctx.region
    kw = {} if region == "us-east-1" else {"CreateBucketConfiguration": {"LocationConstraint": region}}
    s3.create_bucket(Bucket=name, **kw)
    try:
        s3.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
        s3.put_object(Bucket=name, Key="probe.txt", Body=b"probe")
        job = ctx.backup.start_backup_job(BackupVaultName=ctx.vault, ResourceArn=f"arn:aws:s3:::{name}",
                                          IamRoleArn=ctx.role_arn, IdempotencyToken=str(uuid.uuid4()),
                                          Lifecycle={"DeleteAfterDays": 1})
        while True:
            d = ctx.backup.describe_backup_job(BackupJobId=job["BackupJobId"])
            if d["State"] in ("COMPLETED", "FAILED", "ABORTED", "EXPIRED"):
                break
            time.sleep(20)
        if d["State"] != "COMPLETED":
            log.error("Probe backup ended %s: %s", d["State"], d.get("StatusMessage"))
            return False
        try:
            ctx.backup.delete_recovery_point(BackupVaultName=ctx.vault, RecoveryPointArn=d["RecoveryPointArn"])
        except ClientError as e:
            log.error("FAIL: DeleteRecoveryPoint refused: %s", e)
            return False
        log.info("PASS: probe recovery point deleted successfully.")
        return True
    finally:
        try:
            s3.delete_object(Bucket=name, Key="probe.txt")
            for page in s3.get_paginator("list_object_versions").paginate(Bucket=name):
                for v in page.get("Versions", []) + page.get("DeleteMarkers", []):
                    s3.delete_object(Bucket=name, Key=v["Key"], VersionId=v["VersionId"])
            s3.delete_bucket(Bucket=name)
        except ClientError as e:
            log.warning("Could not remove probe bucket %s: %s", name, e)


def main() -> None:
    p = base_parser("Check that recovery points in the demo vault are deletable.")
    p.add_argument("--deep", action="store_true", help="Create and delete a tiny real recovery point (authoritative, catches SCPs)")
    ctx = Ctx(a := p.parse_args())
    ok = static_checks(ctx)
    if a.deep:
        ok = deep_check(ctx) and ok
    else:
        log.info("Tip: run with --deep for the authoritative check (static checks cannot see SCPs).")
    ctx.write_result("vault-check.json", {"deletable": ok, "deep": a.deep})
    log.info("Vault deletable check: %s", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
