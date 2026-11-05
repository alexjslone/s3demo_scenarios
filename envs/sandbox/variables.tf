variable "demo_id" {
  type        = string
  description = "Unique stack id, lowercase, 3 to 12 chars."

  validation {
    condition     = can(regex("^[a-z0-9]{3,12}$", var.demo_id))
    error_message = "demo_id must be 3 to 12 lowercase letters or digits."
  }
}

variable "region" {
  type        = string
  description = "Region of the sandbox account; must match the region the Clumio connection covers."

  validation {
    condition     = length(var.region) > 0
    error_message = "region is required."
  }
}

variable "state_bucket" {
  type        = string
  description = "EXISTING S3 bucket holding Terraform state (consumed by demo.ps1 at init; use bootstrap/ if none exists)."

  validation {
    condition     = length(var.state_bucket) > 0
    error_message = "state_bucket is required."
  }
}

variable "state_region" {
  type        = string
  description = "Region of the state bucket (consumed by demo.ps1 at init)."

  validation {
    condition     = length(var.state_region) > 0
    error_message = "state_region is required."
  }
}

variable "owner" {
  type        = string
  description = "Owner tag, e.g. your email or alias."

  validation {
    condition     = length(var.owner) > 0
    error_message = "owner is required."
  }
}

variable "expires_on" {
  type        = string
  description = "ExpiresOn tag, YYYY-MM-DD. The nightly workflow tears down expired stacks."

  validation {
    condition     = can(regex("^\\d{4}-\\d{2}-\\d{2}$", var.expires_on))
    error_message = "expires_on must be YYYY-MM-DD."
  }
}

variable "backup_role_arn" {
  type        = string
  default     = null
  description = "Optional EXISTING IAM role AWS Backup can assume. When null a per-stack role is created."
}

variable "datasets" {
  type = map(object({
    kms_key_arn                = optional(string)
    noncurrent_expiration_days = optional(number)
  }))
  default     = { data = {} }
  description = "Data buckets for this stack, keyed by suffix (bucket = s3demo-<demo_id>-<key>). Must include 'data'."

  validation {
    condition     = contains(keys(var.datasets), "data")
    error_message = "datasets must contain a 'data' key (the scenario 2 bucket)."
  }
}

variable "backup_retention_days" {
  type    = number
  default = 7
}

variable "enable_continuous_backup" {
  type    = bool
  default = true
}
