variable "project_id" {
  description = "GCP project containing the existing jumphost"
  type        = string
}

variable "zone" {
  description = "Zone containing the jumphost"
  type        = string
}

variable "instance_name" {
  description = "Name of the existing jumphost"
  type        = string
}

variable "destination_ip" {
  description = "Expected private IPv4 address of the jumphost on nic0; IAP access follows this address"
  type        = string

  validation {
    condition     = can(cidrnetmask("${var.destination_ip}/32"))
    error_message = "destination_ip must be an IPv4 address without a CIDR prefix."
  }
}

variable "iap_users" {
  description = "User accounts to grant IAP access to destination_ip on TCP/22"
  type        = set(string)

  validation {
    condition     = alltrue([for user in var.iap_users : can(regex("^user:[^[:space:]@]+@[^[:space:]@]+[.][^[:space:]@]+$", user))])
    error_message = "Each member must use the format user:email-address."
  }
}
