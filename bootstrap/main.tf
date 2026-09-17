terraform {
  required_version = ">= 1.7.0, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.2"
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
  # checkov:skip=CKV_GCP_62:Läsningar och skrivningar av state loggas med Cloud Audit Logs (storage_data_read nedan), så ingen separat loggbucket behövs
  name     = "team${var.team_id}-tfstate-${random_id.bucket_suffix.hex}"
  location = "EU"

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  lifecycle_rule {
    condition {
      days_since_noncurrent_time = 7
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


resource "google_project_iam_audit_config" "storage_data_read" {
  project = var.project_id
  service = "storage.googleapis.com"

  audit_log_config {
    log_type = "DATA_READ"
  }

  # Skrivningar till state och sparade deployplaner ska gå att spåra (#83).
  audit_log_config {
    log_type = "DATA_WRITE"
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

resource "google_project_iam_member" "cicd_network_admin" {
  project = var.project_id
  role    = "roles/compute.networkAdmin"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

# Ersätter roles/editor (#10). Anpassade roller går inte att skapa i projektet
# (vi saknar iam.roles.create), så det här är de minsta färdiga rollerna som
# täcker rotmodulen: instanser, disk och resource policy (instanceAdmin.v1)
# och brandväggarnas skrivrätt, som networkAdmin inte har (securityAdmin).
# Båda har setIamPolicy på Compute-resurser i hela det delade projektet,
# vilket editor inte har. Avvägningen står i #10.
resource "google_project_iam_member" "cicd_instance_admin" {
  project = var.project_id
  role    = "roles/compute.instanceAdmin.v1"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_project_iam_member" "cicd_security_admin" {
  project = var.project_id
  role    = "roles/compute.securityAdmin"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

# Jumphosten kör som team5-jumphost (#46), så CI behöver actAs på just det
# kontot för att kunna skapa om eller ändra instansen.
resource "google_service_account_iam_member" "cicd_jumphost_user" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/team${var.team_id}-jumphost@${var.project_id}.iam.gserviceaccount.com"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.cicd.email}"
}

# Systemloggar från VM:arna till Cloud Logging (#92). Kontona får bara skriva
# loggar. Primary hade inget konto tidigare och får ett eget för det här.
resource "google_service_account" "primary" {
  account_id   = "team${var.team_id}-primary"
  display_name = "Team ${var.team_id} primary VM (endast loggskrivning)"
}

resource "google_project_iam_member" "vm_log_writers" {
  for_each = {
    jumphost = "serviceAccount:team${var.team_id}-jumphost@${var.project_id}.iam.gserviceaccount.com"
    primary  = google_service_account.primary.member
  }

  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = each.value
}

# CI behöver actAs för att koppla kontot till primary, som för jumphosten.
resource "google_service_account_iam_member" "cicd_primary_user" {
  service_account_id = google_service_account.primary.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.cicd.email}"
}

data "google_iam_policy" "terraform_state" {
  binding {
    role = "roles/storage.objectAdmin"

    members = [
      "serviceAccount:${google_service_account.cicd.email}"
    ]

    condition {
      title       = "cicd_root_state_and_deploy_plans"
      description = "Allow CI/CD to manage root Terraform state and saved deploy plans"
      expression = trimspace(templatefile("${path.module}/cicd-storage-condition.cel.tftpl", {
        root_state_prefix   = jsonencode("projects/_/buckets/${google_storage_bucket.terraform_state.name}/objects/terraform/state/")
        deploy_plans_prefix = jsonencode("projects/_/buckets/${google_storage_bucket.terraform_state.name}/objects/terraform/deploy-plans/")
      }))
    }
  }

  # GCS evaluates object listing against the bucket, not individual object names.
  # This permits listing all names, but does not grant access to object contents.
  binding {
    role    = "roles/storage.legacyBucketReader"
    members = ["serviceAccount:${google_service_account.cicd.email}"]
  }

  binding {
    role = "roles/storage.legacyBucketOwner"

    members = [
      "projectOwner:${var.project_id}"
    ]
  }

  binding {
    role = "roles/storage.legacyObjectOwner"

    members = [
      "projectOwner:${var.project_id}"
    ]
  }

  binding {
    role = "roles/storage.objectAdmin"

    members = [
      for member in var.team_members : "user:${member}"
    ]
  }

  # objectAdmin räcker bara till objekten. Utan den här bindningen tappar teamet
  # storage.buckets.get, getIamPolicy och setIamPolicy i samma stund som policyn
  # ersätter projectEditor. Då går bootstrap varken att planera eller rulla
  # tillbaka av någon annan än projektägarna.
  binding {
    role = "roles/storage.legacyBucketOwner"

    members = [
      for member in var.team_members : "user:${member}"
    ]
  }
}

resource "google_storage_bucket_iam_policy" "terraform_state" {
  bucket      = google_storage_bucket.terraform_state.name
  policy_data = data.google_iam_policy.terraform_state.policy_data
}

resource "google_service_account_iam_member" "cicd_workload_identity" {
  service_account_id = google_service_account.cicd.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}
