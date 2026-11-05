# Partial backend config. bucket, region and key are supplied at init time by demo.ps1:
#   terraform init -reconfigure -backend-config="bucket=<state_bucket>" \
#     -backend-config="region=<state_region>" -backend-config="key=scenario-2/<demo_id>.tfstate"
terraform {
  backend "s3" {
    use_lockfile = true
    encrypt      = true
  }
}
