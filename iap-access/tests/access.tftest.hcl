# Endast mockad plan: inga GCP-anrop eller riktiga tilldelningar.
mock_provider "google" {}

override_data {
  target = data.google_compute_instance.jumphost
  values = {
    network_interface = [{ network_ip = "10.0.5.2" }]
  }
}

variables {
  project_id     = "test-project"
  zone           = "europe-north2-b"
  instance_name  = "team5-jumphost"
  destination_ip = "10.0.5.2"
  iap_users      = ["user:first@example.com", "user:second@example.com"]
}

run "limited_iap_grants" {
  command = plan

  assert {
    condition = (
      toset([for grant in google_project_iam_member.iap_ssh : grant.member]) == var.iap_users &&
      alltrue([for grant in google_project_iam_member.iap_ssh :
        grant.project == "test-project" &&
        grant.role == "roles/iap.tunnelResourceAccessor" &&
        grant.condition[0].expression == "resource.type == 'iap.googleapis.com/TunnelInstance' && destination.ip == '10.0.5.2' && destination.port == 22"
      ])
    )
    error_message = "Only the specified users should receive the IAP role, restricted to the expected resource type, IP address, and port 22."
  }
}

run "reject_wrong_destination" {
  command = plan
  variables {
    destination_ip = "10.0.6.2"
  }
  expect_failures = [google_project_iam_member.iap_ssh]
}

run "reject_group_or_missing_prefix" {
  command = plan
  variables {
    iap_users = ["group:team@example.com", "person@example.com"]
  }
  expect_failures = [var.iap_users]
}

run "reject_invalid_ip" {
  command = plan
  variables {
    destination_ip = "10.0.5.2/24"
  }
  expect_failures = [var.destination_ip]
}
