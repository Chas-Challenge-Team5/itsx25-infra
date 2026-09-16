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
    condition = (
      keys(google_compute_instance_iam_member.primary_os_admin_logins) == keys(google_compute_instance_iam_member.os_admin_logins) &&
      alltrue([
        for identity, grant in google_compute_instance_iam_member.primary_os_admin_logins :
        grant.project == "itsx25-lab" &&
        grant.zone == "europe-north2-b" &&
        grant.instance_name == "team5-primary" &&
        grant.role == "roles/compute.osAdminLogin" &&
        grant.member == identity
      ])
    )
    error_message = "The same five members must have sudo on Team 5's primary, and nothing else."
  }

}

run "reject_invalid_identity" {
  command = plan
  variables {
    # Intentionally invalid prefix: validation must reject this instead of user:email.
    os_admin_users = ["viktor:viktor.myhre@chasacademy.se"]
  }
  expect_failures = [var.os_admin_users]
}

run "service_account_access" {
  command = plan

  assert {
    condition     = length(google_service_account_iam_member.jumphost_service_account_users) == 5
    error_message = "All five team members need Service Account User when the jumphost has a service account."
  }

  assert {
    condition = alltrue([
      for identity, grant in google_service_account_iam_member.jumphost_service_account_users :
      grant.service_account_id == "projects/itsx25-lab/serviceAccounts/team5-jumphost@itsx25-lab.iam.gserviceaccount.com" &&
      grant.role == "roles/iam.serviceAccountUser" &&
      grant.member == identity &&
      grant.member == google_compute_instance_iam_member.os_admin_logins[identity].member
    ])
    error_message = "Service Account User must target only the jumphost account and the same identities as OS Login."
  }
}
