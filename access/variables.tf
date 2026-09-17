variable "os_admin_users" {
  description = "Google user identities granted OS Login sudo access on Team 5's jumphost and primary, and Service Account User on their service accounts."
  type        = set(string)

  validation {
    condition     = length(var.os_admin_users) > 0 && alltrue([for member in var.os_admin_users : can(regex("^user:[^@ :]+@[^@ :]+[.][^@ :]+$", member))])
    error_message = "Provide at least one user in the form user:name@example.com."
  }
}
