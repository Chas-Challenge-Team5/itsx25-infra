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

variable "enable_secure_boot" {
  description = "Secure Boot for both jumphost and primary. Enable only after preparing and boot-testing a signed kernel on each disk (scripts/prepare-secure-boot.sh). Changing this setting requires a VM stop/start; a fresh VM from the current lab image must be prepared first."
  type        = bool
  default     = false
}
