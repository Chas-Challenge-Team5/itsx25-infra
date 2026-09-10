terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }

  backend "gcs" {
    bucket = "team5-tfstate-f7036a24"
    prefix = "terraform/bootstrap-state"
  }
}

provider "google" {
  project = var.project_id
}

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "google_storage_bucket" "terraform_state" {
  name     = "team${var.team_id}-tfstate-${random_id.bucket_suffix.hex}"
  location = "EU"

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  lifecycle_rule {
    condition {
      num_newer_versions = 10
    }
    action {
      type = "Delete"
    }
  }

  versioning {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "team${var.team_id}-github-pool"
  display_name              = "GitHub Actions Pool"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "team${var.team_id}-github-provider"
  display_name                       = "GitHub Actions Provider"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
  }

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  # En PR kan ändra sin workflow. Säkerhetsgränsen måste därför ligga i GCP.
  attribute_condition = trimspace(templatefile("${path.module}/github-wif-condition.cel.tftpl", {
    repository    = jsonencode(var.github_repo)
    repository_id = jsonencode(var.github_repository_id)
    owner_id      = jsonencode(var.github_repository_owner_id)
    workflow_ref  = jsonencode("${var.github_repo}/.github/workflows/deploy.yml@refs/heads/main")
  }))
}

resource "google_service_account" "cicd" {
  account_id   = "team${var.team_id}-cicd"
  display_name = "CI/CD Pipeline Service Account"
}

resource "google_project_iam_member" "cicd_editor" {
  project = var.project_id
  role    = "roles/editor"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_service_account_iam_member" "cicd_workload_identity" {
  service_account_id = google_service_account.cicd.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}
