module "prefix" {
  source                     = "../demo-bucket"
  bucket_name                = "s3demo-${var.demo_id}-restore-prefix"
  noncurrent_expiration_days = var.noncurrent_expiration_days
  tags                       = var.tags
}

module "full" {
  source                     = "../demo-bucket"
  bucket_name                = "s3demo-${var.demo_id}-restore-full"
  noncurrent_expiration_days = var.noncurrent_expiration_days
  tags                       = var.tags
}
