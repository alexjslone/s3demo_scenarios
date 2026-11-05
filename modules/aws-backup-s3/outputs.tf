output "vault_name" {
  value = aws_backup_vault.this.name
}

output "vault_arn" {
  value = aws_backup_vault.this.arn
}

output "plan_id" {
  value = aws_backup_plan.this.id
}

output "role_arn" {
  value = local.role_arn
}

output "retention_days" {
  value = var.retention_days
}
