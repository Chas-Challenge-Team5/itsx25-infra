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
  description = "Chas Academy-mailadresser för lagmedlemmar med läsrätt till Terraform state"
  type        = list(string)
}
