# Copy to <demo_id>.tfvars (e.g. jsmith01.tfvars). Never commit real values.
demo_id      = "jsmith01"
region       = "us-east-1"          # must match the Clumio connection region
state_bucket = "my-existing-tfstate-bucket"
state_region = "us-east-1"
owner        = "jsmith@example.com"
expires_on   = "2026-12-31"

# Optional: reuse an existing role AWS Backup can assume (otherwise a per-stack role is created)
# backup_role_arn = "arn:aws:iam::123456789012:role/existing-aws-backup-role"

# Optional: extra data buckets for future scenarios (the "data" key is required)
# datasets = {
#   data   = {}
#   second = { noncurrent_expiration_days = 30 }
# }
