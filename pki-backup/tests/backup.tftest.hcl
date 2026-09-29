mock_provider "google" {}
override_resource {
  target = google_secret_manager_secret.company_ca
  values = { id = "projects/123456789/secrets/team5-company-ca-backup" }
}
override_data {
  target = data.google_project.lab
  values = { number = "123456789" }
}
variables {
  recovery_users = ["user:operator@chasacademy.se"]
}
run "recovery_is_limited_to_one_secret" {
  command = plan
  assert {
    condition = (
      google_secret_manager_secret.company_ca.secret_id == "team5-company-ca-backup" &&
      google_secret_manager_secret.company_ca.deletion_protection &&
      google_project_iam_member.ca_recovery["user:operator@chasacademy.se"].role == "roles/secretmanager.secretAccessor" &&
      google_project_iam_member.ca_recovery["user:operator@chasacademy.se"].condition[0].expression == "resource.service == 'secretmanager.googleapis.com' && (resource.name == 'projects/123456789/secrets/team5-company-ca-backup' || resource.name.startsWith('projects/123456789/secrets/team5-company-ca-backup/versions/'))"
    )
    error_message = "Recovery access must be limited to the protected company CA secret and its versions."
  }
}
run "private_account_is_rejected" {
  command = plan
  variables {
    recovery_users = ["user:private@example.com"]
  }
  expect_failures = [var.recovery_users]
}
