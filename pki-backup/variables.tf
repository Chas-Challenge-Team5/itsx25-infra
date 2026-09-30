variable "recovery_users" {
  type        = set(string)
  description = "School identities allowed to recover this CA. Supply the team list locally; no machine or private Windows identity is required."
  validation {
    condition = length(var.recovery_users) > 0 && alltrue([
      for user in var.recovery_users : can(regex("^user:[a-zA-Z0-9._+-]+@chasacademy\\.se$", user))
    ])
    error_message = "Use school identities in user:name@chasacademy.se format."
  }
}
