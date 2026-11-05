variable "bucket_name" {
  type        = string
  description = "Full bucket name."
}

variable "kms_key_arn" {
  type        = string
  default     = null
  description = "Optional KMS key for default encryption (SSE-S3 when null). If set, the AWS Backup role needs access to this key."
}

variable "noncurrent_expiration_days" {
  type        = number
  default     = null
  description = "Expire noncurrent versions after N days. Null disables the rule (default for the data bucket so the baseline stays intact)."
}

variable "tags" {
  type    = map(string)
  default = {}
}
