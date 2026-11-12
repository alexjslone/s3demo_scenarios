terraform {
  required_version = ">= 1.10"

  required_providers {
    clumio = {
      source  = "clumio-code/clumio"
      version = "~> 0.25"
    }
  }

  # Separate state from envs/sandbox so a destroy here removes ONLY the Clumio protection group,
  # policy and assignment and never touches the bucket or AWS Backup.
  # Run through demo.ps1 (clumio-up / clumio-status / clumio-down), which supplies:
  #   bucket = state_bucket and region = state_region from tfvars/<demo_id>.tfvars
  #   key    = scenario-2/<demo_id>-clumio.tfstate
  backend "s3" {
    use_lockfile = true
    encrypt      = true
  }
}

# Authentication comes from the environment, no secrets in code:
#   $env:CLUMIO_API_TOKEN    = "<personal API token from the Clumio portal>"
#   $env:CLUMIO_API_BASE_URL = "<API base URL for your Clumio portal region, e.g. https://us-east-1.api.clumio.com>"
provider "clumio" {}
