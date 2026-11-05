# IMPORTANT: standard vault, NO Vault Lock, NOT logically air gapped, and NO vault access
# policy denying backup:DeleteRecoveryPoint. Recovery points must stay deletable so the demo
# is repeatable and `terraform destroy` works (see scripts/check_vault_deletable.py).
resource "aws_backup_vault" "this" {
  name = "s3demo-${var.demo_id}-vault"
  tags = var.tags
}

locals {
  create_role = var.role_arn == null
  role_arn    = local.create_role ? aws_iam_role.backup[0].arn : var.role_arn
  managed_policy_arns = [
    "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup",
    "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForRestores",
    "arn:aws:iam::aws:policy/AWSBackupServiceRolePolicyForS3Backup",
    "arn:aws:iam::aws:policy/AWSBackupServiceRolePolicyForS3Restore",
  ]
}

data "aws_iam_policy_document" "assume" {
  count = local.create_role ? 1 : 0
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["backup.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "backup" {
  count              = local.create_role ? 1 : 0
  name               = "s3demo-${var.demo_id}-backup-role"
  assume_role_policy = data.aws_iam_policy_document.assume[0].json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "backup" {
  for_each   = local.create_role ? toset(local.managed_policy_arns) : toset([])
  role       = aws_iam_role.backup[0].name
  policy_arn = each.value
}

resource "aws_backup_plan" "this" {
  name = "s3demo-${var.demo_id}-plan"

  rule {
    rule_name                = "daily"
    target_vault_name        = aws_backup_vault.this.name
    schedule                 = var.schedule
    enable_continuous_backup = var.enable_continuous_backup

    lifecycle {
      delete_after = var.retention_days
    }
  }

  tags = var.tags
}

resource "aws_backup_selection" "this" {
  name         = "s3demo-${var.demo_id}-selection"
  plan_id      = aws_backup_plan.this.id
  iam_role_arn = local.role_arn
  resources    = var.bucket_arns

  depends_on = [aws_iam_role_policy_attachment.backup]
}
