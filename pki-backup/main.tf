terraform {
  required_version = ">= 1.7.0, < 2.0.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.2"
    }
  }
  # Operator-managed metadata/IAM only. Secret payloads never enter Terraform.
  backend "gcs" {
    bucket = "team5-tfstate-f7036a24"
    prefix = "terraform/pki-backup-state"
  }
}

provider "google" {
  project = "itsx25-lab"
}

data "google_project" "lab" {
  project_id = "itsx25-lab"
}

locals {
  secret_resource_name = "projects/${data.google_project.lab.number}/secrets/team5-company-ca-backup"
}

resource "google_secret_manager_secret" "company_ca" {
  project             = "itsx25-lab"
  secret_id           = "team5-company-ca-backup"
  deletion_protection = true
  labels              = { team = "5", purpose = "company-ca-recovery" }
  replication {
    user_managed {
      replicas {
        location = "europe-north2"
      }
    }
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_project_iam_member" "ca_recovery" {
  for_each = var.recovery_users
  project  = "itsx25-lab"
  role     = "roles/secretmanager.secretAccessor"
  member   = each.value

  # Project IAM is available to the operators; direct Secret IAM writes are not.
  # Match exactly this Secret and its versions, never a shared team-name prefix.
  condition {
    title       = "team5-company-ca-recovery"
    description = "Read only the Team 5 company CA recovery bundle."
    expression  = "resource.service == 'secretmanager.googleapis.com' && (resource.name == '${local.secret_resource_name}' || resource.name.startsWith('${local.secret_resource_name}/versions/'))"
  }
}

output "secret_name" {
  value = local.secret_resource_name
}
