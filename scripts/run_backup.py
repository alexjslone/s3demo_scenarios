"""Start an on-demand AWS Backup job for the data bucket and wait for completion."""
from __future__ import annotations

import time
import uuid

from common import Ctx, base_parser, fmt_dur, iso, log, utcnow

TERMINAL = {"COMPLETED", "FAILED", "EXPIRED", "ABORTED", "PARTIAL"}


def main() -> None:
    p = base_parser("Run an on-demand AWS Backup job and record its duration.")
    p.add_argument("--poll", type=int, default=30)
    p.add_argument("--timeout-min", type=int, default=240)
    ctx = Ctx(a := p.parse_args())
    ctx.check_tags(ctx.data_bucket)
    arn = ctx.out["data_bucket_arn"]
    start = utcnow()
    job = ctx.backup.start_backup_job(
        BackupVaultName=ctx.vault, ResourceArn=arn, IamRoleArn=ctx.role_arn,
        IdempotencyToken=str(uuid.uuid4()),
        Lifecycle={"DeleteAfterDays": int(ctx.out.get("backup_retention_days", 7))},
    )
    job_id = job["BackupJobId"]
    log.info("Started backup job %s", job_id)
    deadline = time.time() + a.timeout_min * 60
    while True:
        d = ctx.backup.describe_backup_job(BackupJobId=job_id)
        st = d["State"]
        log.info("state=%s %s", st, d.get("PercentDone", ""))
        if st in TERMINAL:
            break
        if time.time() > deadline:
            raise SystemExit("Timed out waiting for backup job.")
        time.sleep(a.poll)
    end = utcnow()
    res = {"backup_job_id": job_id, "state": st, "recovery_point_arn": d.get("RecoveryPointArn"),
           "start": iso(start), "end": iso(end), "duration_s": (end - start).total_seconds(),
           "bytes": d.get("BackupSizeInBytes"), "message": d.get("StatusMessage")}
    ctx.write_result("backup.json", res)
    log.info("Backup %s in %s", st, fmt_dur(res["duration_s"]))
    if st != "COMPLETED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
