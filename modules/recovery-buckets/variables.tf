variable "demo_id" {
  type = string
}

variable "noncurrent_expiration_days" {
  type    = number
  default = 1
}

variable "tags" {
  type    = map(string)
  default = {}
}
