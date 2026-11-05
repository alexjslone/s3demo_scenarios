locals {
  tags = {
    Project   = "s3-demo"
    Scenario  = "scenario-2"
    DemoId    = var.demo_id
    Owner     = var.owner
    ExpiresOn = var.expires_on
  }
}

module "dataset_bucket" {
  source   = "../../modules/demo-bucket"
  for_each = var.datasets

  bucket_name                = "s3demo-${var.demo_id}-${each.key}"
  kms_key_arn                = each.value.kms_key_arn
  noncurrent_expiration_days = each.value.noncurrent_expiration_days
  tags                       = local.tags
}

module "recovery_buckets" {
  source  = "../../modules/recovery-buckets"
  demo_id = var.demo_id
  tags    = local.tags
}

module "aws_backup" {
  source = "../../modules/aws-backup-s3"

  demo_id                  = var.demo_id
  bucket_arns              = [for b in module.dataset_bucket : b.arn]
  role_arn                 = var.backup_role_arn
  retention_days           = var.backup_retention_days
  enable_continuous_backup = var.enable_continuous_backup
  tags                     = local.tags
}
