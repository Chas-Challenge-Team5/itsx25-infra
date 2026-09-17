# All resources are mocked. Nothing is created in GCP.
mock_provider "google" {
  mock_data "google_iam_policy" {
    defaults = {
      policy_data = "{}"
    }
  }
}

mock_provider "random" {}

override_resource {
  target          = google_service_account.cicd
  override_during = plan
  values = {
    email = "team5-cicd@test-project.iam.gserviceaccount.com"
    name  = "projects/test-project/serviceAccounts/team5-cicd@test-project.iam.gserviceaccount.com"
  }
}

override_resource {
  target          = google_service_account.primary
  override_during = plan
  values = {
    email  = "team5-primary@test-project.iam.gserviceaccount.com"
    member = "serviceAccount:team5-primary@test-project.iam.gserviceaccount.com"
    name   = "projects/test-project/serviceAccounts/team5-primary@test-project.iam.gserviceaccount.com"
  }
}

variables {
  project_id                 = "test-project"
  team_id                    = 5
  github_repo                = "example/repo"
  github_repository_id       = "1"
  github_repository_owner_id = "2"
  team_members               = ["member@example.com"]
}

# VM-kontona får bara skriva loggar (#92).
run "vm_accounts_only_write_logs" {
  command = plan

  assert {
    condition     = google_service_account.primary.account_id == "team5-primary"
    error_message = "Primary must get its own account, team5-primary."
  }

  assert {
    condition = (
      keys(google_project_iam_member.vm_log_writers) == ["jumphost", "primary"] &&
      alltrue([for grant in google_project_iam_member.vm_log_writers : grant.role == "roles/logging.logWriter"]) &&
      google_project_iam_member.vm_log_writers["jumphost"].member == "serviceAccount:team5-jumphost@test-project.iam.gserviceaccount.com" &&
      google_project_iam_member.vm_log_writers["primary"].member == "serviceAccount:team5-primary@test-project.iam.gserviceaccount.com"
    )
    error_message = "Both VM accounts must get roles/logging.logWriter and nothing else from this block."
  }

  assert {
    condition = (
      google_service_account_iam_member.cicd_primary_user.service_account_id == "projects/test-project/serviceAccounts/team5-primary@test-project.iam.gserviceaccount.com" &&
      google_service_account_iam_member.cicd_primary_user.role == "roles/iam.serviceAccountUser" &&
      google_service_account_iam_member.cicd_primary_user.member == "serviceAccount:team5-cicd@test-project.iam.gserviceaccount.com"
    )
    error_message = "CI must get Service Account User on the primary account."
  }
}
