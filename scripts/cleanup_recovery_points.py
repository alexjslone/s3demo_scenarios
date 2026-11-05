"""Delete all recovery points in the demo vault so `terraform destroy` can remove it."""
from __future__ import annotations

import time

from botocore.exceptions import ClientError

from common import Ctx, base_parser, log


def main() -> None:
    p = base_parser("Delete every recovery point in the demo vault.", destructive=True)
    ctx = Ctx(a := p.parse_args())
    expected = f"s3demo-{ctx.demo_id}-vault"
    if ctx.vault != expected:
        raise SystemExit(f"Vault {ctx.vault} does not match expected {expected}; refusing.")
    arn = ctx.backup.describe_backup_vault(BackupVaultName=ctx.vault)["BackupVaultArn"]
    tags = ctx.backup.list_tags(ResourceArn=arn).get("Tags", {})
    if tags.get("Project") != "s3-demo" or tags.get("DemoId") != ctx.demo_id:
        raise SystemExit("Vault is not tagged Project=s3-demo / matching DemoId; refusing.")

    for j in ctx.backup.get_paginator("list_backup_jobs").paginate(ByBackupVaultName=ctx.vault, ByState="RUNNING"):
        for job in j["BackupJobs"]:
            log.info("Stopping running job %s", job["BackupJobId"])
            ctx.backup.stop_backup_job(BackupJobId=job["BackupJobId"])

    for attempt in range(10):
        pts = [r["RecoveryPointArn"] for pg in ctx.backup.get_paginator("list_recovery_points_by_backup_vault")
               .paginate(BackupVaultName=ctx.vault) for r in pg["RecoveryPoints"]]
        if not pts:
            log.info("Vault is empty.")
            return
        log.info("Deleting %d recovery points (pass %d)", len(pts), attempt + 1)
        for rp in pts:
            try:
                ctx.backup.delete_recovery_point(BackupVaultName=ctx.vault, RecoveryPointArn=rp)
            except ClientError as e:
                log.warning("Delete %s: %s", rp, e.response["Error"]["Code"])
        time.sleep(15)
    raise SystemExit("Recovery points remain after retries; re-run later (deletion can be asynchronous).")


if __name__ == "__main__":
    main()
