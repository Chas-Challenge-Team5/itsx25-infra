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

variable "team_members" {
  description = "Chas Academy-mailadresser för lagmedlemmar som förvaltar bucketen och Terraform state"
  type        = list(string)
}

variable "retire_legacy_cicd_roles" {
  description = "Remove the legacy CI Editor and Network Admin grants only after the custom deploy role has been applied and independently verified."
  type        = bool
  default     = false
}
