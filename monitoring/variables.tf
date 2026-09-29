variable "notification_emails" {
  description = "Recipients keyed by a stable alias. Supply school email addresses in the ignored monitoring/terraform.tfvars file; addresses also exist in the private Terraform state."
  type        = map(string)

  validation {
    condition = length(var.notification_emails) > 0 && alltrue([
      for alias, email in var.notification_emails :
      can(regex("^[a-z][a-z0-9_-]*$", alias)) &&
      can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", email))
    ])
    error_message = "Provide at least one recipient with a simple alias and a valid email address."
  }
}
