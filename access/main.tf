terraform {
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
