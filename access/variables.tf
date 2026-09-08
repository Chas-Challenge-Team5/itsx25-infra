variable "os_admin_users" {
  description = "Google user identities granted sudo through OS Login on Team 5's jumphost."
  type        = set(string)

  validation {
    condition     = length(var.os_admin_users) > 0 && alltrue([for member in var.os_admin_users : can(regex("^user:[^@ :]+@[^@ :]+[.][^@ :]+$", member))])
    error_message = "Provide at least one user in the form user:name@example.com."
  }
}
