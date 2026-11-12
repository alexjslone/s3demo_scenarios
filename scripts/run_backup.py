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
    p.add_argument("--result-name", default="backup.json",
                   help="Result file name. Keep the default for the baseline backup (restores use it); "
                        "use e.g. backup-post-incident.json for any later backup.")
    p.add_argument("--no-index", action="store_true", help="Do not request an S3 backup index")
    ctx = Ctx(a := p.parse_args())
    ctx.check_tags(ctx.data_bucket)
    arn = ctx.out["data_bucket_arn"]
    start = utcnow()
    job = ctx.backup.start_backup_job(
        BackupVaultName=ctx.vault, ResourceArn=arn, IamRoleArn=ctx.role_arn,
        IdempotencyToken=str(uuid.uuid4()),
        Index="DISABLED" if a.no_index else "ENABLED",  # on-demand jobs ignore the plan's IndexActions
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
    ctx.write_result(a.result_name, res)
    log.info("Backup %s in %s", st, fmt_dur(res["duration_s"]))
    if st != "COMPLETED":
        raise SystemExit(1)
    if not a.no_index and res["recovery_point_arn"]:
        # Indexing runs after the backup completes; searches only see ACTIVE indexes.
        for _ in range(120):
            rp = ctx.backup.describe_recovery_point(BackupVaultName=ctx.vault, RecoveryPointArn=res["recovery_point_arn"])
            ist = rp.get("IndexStatus")
            log.info("index status=%s", ist)
            if ist in (None, "ACTIVE", "FAILED"):
                break
            time.sleep(a.poll)
        ctx.write_result(a.result_name, {**res, "index_status": ist, "index_ready": iso(utcnow())})


if __name__ == "__main__":
    main()
