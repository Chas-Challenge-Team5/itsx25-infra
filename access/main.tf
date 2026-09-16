terraform {
  required_version = ">= 1.7.0, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }

  backend "gcs" {
    bucket = "team5-tfstate-f7036a24"
    prefix = "terraform/access-state"
  }
}

provider "google" {
  project = "itsx25-lab"
}

# Admin-managed access to the existing VM; this module does not modify the VM.
resource "google_compute_instance_iam_member" "os_admin_logins" {
  for_each = var.os_admin_users

  project       = "itsx25-lab"
  zone          = "europe-north2-b"
  instance_name = "team5-jumphost"
  role          = "roles/compute.osAdminLogin"
  member        = each.value
}

# Primary is created by the root module, so apply this after the deploy that creates it.
# Without this grant sudo on primary depends on the class group's project-wide editor role.
resource "google_compute_instance_iam_member" "primary_os_admin_logins" {
  for_each = var.os_admin_users

  project       = "itsx25-lab"
  zone          = "europe-north2-b"
  instance_name = "team5-primary"
  role          = "roles/compute.osAdminLogin"
  member        = each.value
}

# OS Login also requires Service Account User when #46 attaches this account.
# Manage these grants separately before enabling OS Login with the attached account.
resource "google_service_account_iam_member" "jumphost_service_account_users" {
  for_each = var.os_admin_users

  service_account_id = "projects/itsx25-lab/serviceAccounts/team5-jumphost@itsx25-lab.iam.gserviceaccount.com"
  role               = "roles/iam.serviceAccountUser"
  member             = each.value
}
