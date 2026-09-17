# All resources are mocked. No VMs are created.
mock_provider "google" {}

override_resource {
  target = google_compute_firewall.allow_ssh_iap
  values = { id = "projects/test-project/global/firewalls/team5-allow-ssh-iap" }
}

override_resource {
  target = google_compute_firewall.allow_ssh_instructor
  values = { id = "projects/test-project/global/firewalls/team5-allow-ssh-jumphost" }
}

override_data {
  target = data.google_compute_zones.available
  values = { names = ["europe-north2-a", "europe-north2-b", "europe-north2-c"] }
}

variables {
  project_id = "test-project"
  team_id    = 5
}

# Systemjournalen från båda VM:arna till Cloud Logging (#92).
run "both_instances_install_ops_agent" {
  command = plan

  assert {
    condition = alltrue([
      for script in [
        google_compute_instance.jumphost.metadata["startup-script"],
        google_compute_instance.primary.metadata["startup-script"],
        ] : (
        strcontains(script, base64encode(local.ops_agent_script)) &&
        strcontains(script, "/usr/local/sbin/team-ops-agent || echo")
      )
    ])
    error_message = "Both startup scripts must install and run the Ops Agent helper without aborting on failure."
  }

  assert {
    condition = (
      strcontains(local.ops_agent_script, filebase64("${path.module}/templates/ops-agent-config.yaml")) &&
      strcontains(local.ops_agent_script, "signed-by=/etc/apt/keyrings/google-keyring.gpg")
    )
    error_message = "The helper must carry the reviewed configuration and use the signed Google repository."
  }

  assert {
    condition = (
      google_compute_instance.jumphost.service_account[0].email == "team5-jumphost@test-project.iam.gserviceaccount.com" &&
      google_compute_instance.primary.service_account[0].email == "team5-primary@test-project.iam.gserviceaccount.com" &&
      google_compute_instance.primary.service_account[0].scopes == toset(["https://www.googleapis.com/auth/logging.write"])
    )
    error_message = "The agent needs each VM's own account, and primary's token must be limited to writing logs."
  }
}
