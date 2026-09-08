mock_provider "google" {}

run "team5_access" {
  command = plan

  assert {
    condition     = length(google_compute_instance_iam_member.os_admin_logins) == 5
    error_message = "All five team members must retain sudo access."
  }

  assert {
    condition = alltrue([
      for grant in google_compute_instance_iam_member.os_admin_logins :
      grant.project == "itsx25-lab" &&
      grant.zone == "europe-north2-b" &&
      grant.instance_name == "team5-jumphost" &&
      grant.role == "roles/compute.osAdminLogin"
    ])
    error_message = "Access must be limited to Team 5's jumphost."
  }

  assert {
    condition     = contains(keys(google_compute_instance_iam_member.os_admin_logins), "user:hakim.abdi@chasacademy.se")
    error_message = "Abdi must be included in the access migration."
  }
}

run "reject_invalid_identity" {
  command = plan
  variables {
    os_admin_users = ["viktor:viktor.myhre@chasacademy.se"]
  }
  expect_failures = [var.os_admin_users]
}
