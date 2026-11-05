"""Run and time an AWS Backup S3 restore: in-place | prefix | full.

Restores are NON-DESTRUCTIVE: in-place does not overwrite existing (corrupted) objects.
"""
from __future__ import annotations

import json
import time

from common import Ctx, base_parser, fmt_dur, iso, list_current, load_manifest, log, parse_iso, utcnow

TERMINAL = {"COMPLETED", "FAILED", "ABORTED", "EXPIRED"}
# Metadata key for restoring additional object versions. Verify against the current AWS Backup
# "Restore S3 data" docs before a customer run; override with --extra-metadata if it changes.
VERSIONS_KEY = "RestoreLatestVersionsUpTo"


def pick_recovery_point(ctx: Ctx) -> str:
    rec = ctx.read_result("backup.json")
    if rec and rec.get("recovery_point_arn"):
        log.info("Using recovery point from run_backup: %s", rec["recovery_point_arn"])
        return rec["recovery_point_arn"]
    inc = ctx.read_result("incident.json")
    kw = {"BackupVaultName": ctx.vault, "ByResourceArn": ctx.out["data_bucket_arn"]}
    if inc:
        kw["ByCreatedBefore"] = parse_iso(inc["incident_start"])
    pts = [r for p in ctx.backup.get_paginator("list_recovery_points_by_backup_vault").paginate(**kw)
           for r in p["RecoveryPoints"] if r["Status"] == "COMPLETED"]
    if not pts:
        raise SystemExit("No completed recovery point found. Run `demo.ps1 backup` first.")
    pts.sort(key=lambda r: r["CreationDate"], reverse=True)
    return pts[0]["RecoveryPointArn"]


def main() -> None:
    p = base_parser("Time an AWS Backup S3 restore.")
    p.add_argument("--mode", required=True, choices=["in-place", "prefix", "full"])
    p.add_argument("--prefixes", nargs="*", default=["finance/"], help="prefix mode: up to 5 keys/prefixes")
    p.add_argument("--recovery-point-arn")
    p.add_argument("--versions", choices=["latest", "10", "all"], default="latest")
    p.add_argument("--restore-time", help="UTC ISO time; REQUIRED only for continuous recovery points")
    p.add_argument("--extra-metadata", nargs="*", default=[], help="key=value pairs added to restore metadata")
    p.add_argument("--poll", type=int, default=20)
    p.add_argument("--timeout-min", type=int, default=480)
    ctx = Ctx(a := p.parse_args())
    if a.mode == "prefix" and not 1 <= len(a.prefixes) <= 5:
        raise SystemExit("prefix mode accepts 1 to 5 prefixes/keys (ItemsToRestore limit).")

    dest = {"in-place": ctx.data_bucket, "prefix": ctx.prefix_bucket, "full": ctx.full_bucket}[a.mode]
    ctx.check_tags(dest)
    if a.mode != "in-place" and next(list_current(ctx.s3, dest, ""), None):
        raise SystemExit(f"Recovery bucket {dest} is not empty. Run `demo.ps1 reset` first.")

    meta = {"DestinationBucketName": dest}
    if a.mode == "prefix":
        meta["ItemsToRestore"] = json.dumps(a.prefixes)
    if a.restore_time:
        meta["RestoreTime"] = a.restore_time
    if a.versions != "latest":
        meta[VERSIONS_KEY] = "all" if a.versions == "all" else "10"
    meta.update(kv.split("=", 1) for kv in a.extra_metadata)

    rp = a.recovery_point_arn or pick_recovery_point(ctx)
    start = utcnow()
    job_id = ctx.backup.start_restore_job(RecoveryPointArn=rp, IamRoleArn=ctx.role_arn,
                                          Metadata=meta, ResourceType="S3")["RestoreJobId"]
    log.info("Started %s restore job %s -> %s", a.mode, job_id, dest)
    deadline = time.time() + a.timeout_min * 60
    while True:
        d = ctx.backup.describe_restore_job(RestoreJobId=job_id)
        log.info("status=%s %s", d["Status"], d.get("PercentDone", ""))
        if d["Status"] in TERMINAL:
            break
        if time.time() > deadline:
            raise SystemExit("Timed out waiting for restore job.")
        time.sleep(a.poll)
    end = utcnow()

    scope = a.prefixes if a.mode == "prefix" else ["(whole bucket)"]
    if a.mode == "in-place":
        base = load_manifest(ctx.manifest_path)
        sel = [r for k, r in base.items() if any(k.startswith(x) for x in a.prefixes)] or list(base.values())
        objs, size = len(sel), sum(int(r["size"]) for r in sel)
        note = "in-place: counts are from the baseline manifest; existing objects are NOT overwritten"
    else:
        objs = size = 0
        for _, sz in list_current(ctx.s3, dest, ""):
            objs += 1
            size += sz
        note = ""
    res = {"mode": a.mode, "restore_job_id": job_id, "status": d["Status"], "message": d.get("StatusMessage"),
           "recovery_point_arn": rp, "destination": dest, "scope": scope, "versions": a.versions,
           "start": iso(start), "end": iso(end), "duration_s": (end - start).total_seconds(),
           "objects": objs, "bytes": size, "note": note}
    ctx.write_result(f"restore-{a.mode}.json", res)
    log.info("Restore %s in %s (%d objects)", d["Status"], fmt_dur(res["duration_s"]), objs)
    if d["Status"] != "COMPLETED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
