terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.60, < 7.0"
    }
  }
}

# Auth comes from the operator's AWS_PROFILE / SSO session. Never hardcode keys.
provider "aws" {
  region = var.region

  default_tags {
    tags = local.tags
  }
}
