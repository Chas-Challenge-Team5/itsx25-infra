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

# Spectre via tailnätet (#51).
run "spectre_nat_and_split_dns" {
  command = plan

  assert {
    condition = strcontains(
      local.nat_firewall_script,
      "-o \"$interface\" -s '100.64.0.0/10' -d '10.0.0.2/32' -j MASQUERADE"
    )
    error_message = "Only tailnet traffic to Spectre may be masqueraded on the jumphost's uplink."
  }

  assert {
    condition = local.dnsmasq_config == join("\n", [
      "interface=tailscale0",
      "bind-dynamic",
      "no-resolv",
      "no-hosts",
      "server=/itsx25.chas-lab.dev/169.254.169.254",
      "",
    ])
    error_message = "dnsmasq must answer only on tailscale0 and only forward the lab zone to GCP's DNS."
  }

  assert {
    condition = (
      strcontains(google_compute_instance.jumphost.metadata["startup-script"], base64encode(local.dnsmasq_config)) &&
      strcontains(google_compute_instance.jumphost.metadata["startup-script"], base64encode(local.nat_firewall_script))
    )
    error_message = "The startup script must install the rendered dnsmasq configuration and firewall helper."
  }
}

run "spectre_follows_proxy_address" {
  command = plan

  variables {
    headscale_proxy_cidr = "10.0.0.9/32"
    lab_dns_zone         = "lab.example.com"
  }

  assert {
    condition = (
      strcontains(local.nat_firewall_script, "-d '10.0.0.9/32' -j MASQUERADE") &&
      !strcontains(local.nat_firewall_script, "10.0.0.2") &&
      strcontains(local.dnsmasq_config, "server=/lab.example.com/169.254.169.254")
    )
    error_message = "Spectre's address and the lab zone must come from variables, not be hardcoded."
  }
}

run "reject_invalid_lab_zone" {
  command = plan

  variables { lab_dns_zone = "Bad Zone." }

  expect_failures = [var.lab_dns_zone]
}
