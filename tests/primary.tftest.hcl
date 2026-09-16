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
  project_id         = "test-project"
  team_id            = 5
  enable_secure_boot = true
}

run "primary_is_internal_and_hardened" {
  command = plan

  assert {
    condition = (
      google_compute_instance.primary.name == "team5-primary" &&
      google_compute_instance.primary.machine_type == "e2-micro" &&
      google_compute_instance.primary.zone == "europe-north2-b" &&
      google_compute_instance.primary.network_interface[0].network_ip == "10.0.5.3" &&
      length(google_compute_instance.primary.network_interface[0].access_config) == 0 &&
      toset(google_compute_instance.primary.tags) == toset(["primary", "no-external-ip"])
    )
    error_message = "Primary must be an e2-micro at 10.0.5.3 in the access module's zone, without external IP, routed via the jumphost."
  }

  assert {
    condition = (
      length(google_compute_instance.primary.service_account) == 0 &&
      google_compute_instance.primary.metadata["enable-oslogin"] == "TRUE" &&
      google_compute_instance.primary.metadata["block-project-ssh-keys"] == "true" &&
      startswith(google_compute_instance.primary.metadata["startup-script"], "#!/bin/bash\n")
    )
    error_message = "Primary must have no service account, OS Login only and a startup script with a valid shebang."
  }

  # Secure Boot stays off even when the jumphost has it, since the lab image kernel is unsigned (#63).
  assert {
    condition = (
      google_compute_instance.primary.shielded_instance_config[0].enable_secure_boot == false &&
      google_compute_instance.primary.shielded_instance_config[0].enable_vtpm == true &&
      google_compute_instance.primary.shielded_instance_config[0].enable_integrity_monitoring == true &&
      google_compute_instance.jumphost.shielded_instance_config[0].enable_secure_boot == true
    )
    error_message = "Primary must keep vTPM and integrity monitoring, with Secure Boot off until its kernel is replaced."
  }
}
