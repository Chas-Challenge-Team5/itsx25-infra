mock_provider "google" {}
mock_provider "random" {}

variables {
  project_id   = "test-project"
  team_id      = 5
  github_repo  = "example/infra"
  team_members = ["operator@example.com"]
}

run "deploy_role_excludes_identity_and_storage_administration" {
  command = plan

  assert {
    condition = alltrue([
      for permission in google_project_iam_custom_role.cicd_deploy.permissions :
      !strcontains(permission, "IamPolicy") &&
      !startswith(permission, "iam.") &&
      !startswith(permission, "storage.") &&
      permission != "compute.instances.setServiceAccount" &&
      (startswith(permission, "compute.") || contains([
        "resourcemanager.projects.get", "serviceusage.services.use"
      ], permission))
    ])
    error_message = "The deploy role must not administer IAM, service accounts, WIF or storage."
  }

  assert {
    condition = alltrue([
      for permission in [
        "compute.firewalls.create", "compute.firewalls.update",
        "compute.firewalls.delete", "compute.firewalls.get",
        "compute.networks.updatePolicy"
      ] : contains(google_project_iam_custom_role.cicd_deploy.permissions, permission)
    ])
    error_message = "The deploy role must include the firewall lifecycle and network policy permissions."
  }
}

run "default_rollout_preserves_existing_grants" {
  command = plan

  assert {
    condition = (
      length(google_project_iam_member.cicd_editor) == 1 &&
      length(google_project_iam_member.cicd_network_admin) == 1
    )
    error_message = "The initial rollout must preserve the existing grants until retirement is explicitly requested."
  }
}

run "explicit_retirement_removes_legacy_grants" {
  command = plan

  variables {
    retire_legacy_cicd_roles = true
  }

  assert {
    condition = (
      length(google_project_iam_member.cicd_editor) == 0 &&
      length(google_project_iam_member.cicd_network_admin) == 0
    )
    error_message = "Explicit retirement must remove both legacy project grants."
  }
}
