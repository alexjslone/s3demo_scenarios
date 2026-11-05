# JSON friendly outputs consumed by scripts/common.py via `terraform output -json`.
output "demo_id" {
  value = var.demo_id
}

output "region" {
  value = var.region
}

output "data_bucket" {
  value = module.dataset_bucket["data"].name
}

output "data_bucket_arn" {
  value = module.dataset_bucket["data"].arn
}

output "data_buckets" {
  value = { for k, b in module.dataset_bucket : k => b.name }
}

output "recovery_bucket_prefix" {
  value = module.recovery_buckets.prefix_bucket
}

output "recovery_bucket_full" {
  value = module.recovery_buckets.full_bucket
}

output "vault_name" {
  value = module.aws_backup.vault_name
}

output "plan_id" {
  value = module.aws_backup.plan_id
}

output "backup_role_arn" {
  value = module.aws_backup.role_arn
}

output "backup_retention_days" {
  value = module.aws_backup.retention_days
}

output "backup_vault_name" {
  value = module.aws_backup.vault_name
}
