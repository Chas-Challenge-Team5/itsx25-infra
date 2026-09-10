variable "project_id" {
  description = "The Google Cloud project ID"
  type        = string
}

variable "team_id" {
  description = "The team ID"
  type        = number
}

variable "github_repo" {
  description = "GitHub repository in 'owner/repo' format allowed to authenticate via WIF"
  type        = string
}

variable "github_repository_id" {
  description = "Immutable numeric GitHub repository ID, represented as a string"
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must contain only digits."
  }
}

variable "github_repository_owner_id" {
  description = "Immutable numeric GitHub organization ID, represented as a string"
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_owner_id))
    error_message = "github_repository_owner_id must contain only digits."
  }
}
