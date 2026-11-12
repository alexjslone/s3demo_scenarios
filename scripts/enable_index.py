"""Turn on AWS Backup S3 backup indexing for this stack's backup plan (idempotent).

Why a script: the Terraform AWS provider's aws_backup_plan rule block does not (as far as verified)
expose IndexActions, so this sets it through the AWS Backup API after `terraform apply`. The provider
does not read IndexActions back, so later applies should not revert it; `demo.ps1 up` re-runs this anyway.
Safe to run when indexing was already enabled by hand: rules that already index S3 are left alone.
"""
from __future__ import annotations

from common import Ctx, base_parser, log


def main() -> None:
    p = base_parser("Enable S3 backup indexing on the stack's backup plan.")
    ctx = Ctx(p.parse_args())
    plan_id = ctx.out["plan_id"]
    got = ctx.backup.get_backup_plan(BackupPlanId=plan_id)
    plan = got["BackupPlan"]
    changed = False
    rules = []
    for r in plan["Rules"]:
        r = {k: v for k, v in r.items() if k != "RuleId"}  # RuleId is output-only
        actions = r.get("IndexActions") or []
        if not any("S3" in a.get("ResourceTypes", []) for a in actions):
            r["IndexActions"] = actions + [{"ResourceTypes": ["S3"]}]
            changed = True
        rules.append(r)
    if not changed:
        log.info("Plan %s already indexes S3 (version %s). Nothing to do.", plan_id, got.get("VersionId"))
        return
    new_plan = {"BackupPlanName": plan["BackupPlanName"], "Rules": rules}
    if plan.get("AdvancedBackupSettings"):
        new_plan["AdvancedBackupSettings"] = plan["AdvancedBackupSettings"]
    res = ctx.backup.update_backup_plan(BackupPlanId=plan_id, BackupPlan=new_plan)
    log.info("Enabled S3 indexing on plan %s (new version %s).", plan_id, res.get("VersionId"))


if __name__ == "__main__":
    main()
