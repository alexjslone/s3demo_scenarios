variable "demo_id" {
  type = string
}

variable "bucket_arns" {
  type        = list(string)
  description = "Whole-bucket ARNs to protect. AWS Backup cannot scope S3 backup to a prefix."
}

variable "role_arn" {
  type        = string
  default     = null
  description = "Existing IAM role AWS Backup can assume. When null, a per-stack role is created."
}

variable "schedule" {
  type    = string
  default = "cron(0 5 * * ? *)"
}

variable "enable_continuous_backup" {
  type    = bool
  default = true
}

variable "retention_days" {
  type    = number
  default = 7

  validation {
    condition     = var.retention_days >= 1
    error_message = "retention_days must be >= 1."
  }
}

variable "tags" {
  type    = map(string)
  default = {}
}
