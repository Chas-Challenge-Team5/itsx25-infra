variable "project_id" {
  description = "The Google Cloud project ID"
  type        = string
}

variable "region" {
  description = "The Google Cloud region"
  type        = string
  default     = "europe-north2"
}

variable "jumphost_zone" {
  description = "Override zone for the jumphost instance. Defaults to the first zone in the region."
  type        = string
  default     = null
}

variable "primary_zone" {
  description = "Override zone for the primary instance. Defaults to the second zone in the region."
  type        = string
  default     = null
}

variable "team_id" {
  description = "The team ID"
  type        = number
}

variable "instructor_cidr" {
  description = "The CIDR range for the instructor's network"
  type        = string
  default     = "10.0.0.0/24"
}

 variable "ssh_users" {
  description = "List of SSH users and their public keys for instance access"
  type = list(object({
    username   = string
    public_key = string
  }))
}

variable "ssh_source_ranges" {
  description = "Source ranges allowed to reach the jumphost on tcp/22. Snäv in denna till lagets faktiska IP-adresser när de är kända."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
