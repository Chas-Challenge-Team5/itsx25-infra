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

# sshd och resolved härdas på båda VM:arna (#86).
run "both_instances_install_host_hardening" {
  command = plan

  assert {
    condition = alltrue([
      for script in [
        google_compute_instance.jumphost.metadata["startup-script"],
        google_compute_instance.primary.metadata["startup-script"],
        ] : (
        strcontains(script, base64encode(local.host_hardening_script)) &&
        strcontains(script, "/usr/local/sbin/team-host-hardening || echo")
      )
    ])
    error_message = "Both startup scripts must install and run the hardening helper without aborting on failure."
  }

  assert {
    condition = (
      strcontains(local.host_hardening_script, filebase64("${path.module}/templates/sshd-team5.conf")) &&
      strcontains(local.host_hardening_script, filebase64("${path.module}/templates/resolved-team5.conf")) &&
      strcontains(local.host_hardening_script, "\"$sshd\" -t -f")
    )
    error_message = "The helper must carry both drop-ins and validate sshd before reloading."
  }

  assert {
    condition = (
      strcontains(file("${path.module}/templates/sshd-team5.conf"), "AuthorizedKeysFile none") &&
      strcontains(file("${path.module}/templates/sshd-team5.conf"), "X11Forwarding no") &&
      strcontains(file("${path.module}/templates/sshd-team5.conf"), "AllowAgentForwarding no") &&
      !strcontains(file("${path.module}/templates/sshd-team5.conf"), "AllowTcpForwarding") &&
      strcontains(file("${path.module}/templates/resolved-team5.conf"), "LLMNR=no")
    )
    error_message = "The drop-ins must disable home-directory keys, X11 and agent forwarding and LLMNR, and leave TCP forwarding for ssh -J."
  }
}
