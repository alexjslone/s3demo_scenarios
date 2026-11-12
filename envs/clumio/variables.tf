variable "demo_id" {
  description = "demo_id of the sandbox stack. The bucket s3demo-<demo_id>-data carries the tag DemoId=<demo_id>, which the protection group uses to find it."
  type        = string
}

variable "excluded_prefixes" {
  description = "Prefixes (relative to the bucket root) Clumio will NOT back up. Include the trailing slash."
  type        = list(string)
  default     = ["app-logs/"]
}

variable "storage_classes" {
  description = "S3 storage classes Clumio backs up."
  type        = set(string)
  default     = ["S3 Standard", "S3 Standard-IA", "S3 Intelligent-Tiering", "S3 One Zone-IA"]
}

variable "retention_days" {
  description = "Retention in days for both the periodic and the continuous backup operations. Clumio requires 30 to 999 for the daily protection group backup."
  type        = number
  default     = 31

  validation {
    condition     = var.retention_days >= 30 && var.retention_days <= 999
    error_message = "retention_days must be between 30 and 999 (Clumio limit for a daily protection group backup)."
  }
}

variable "continuous_rpo_minutes" {
  description = "Continuous backup RPO in minutes."
  type        = number
  default     = 15
}
