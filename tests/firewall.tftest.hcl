# All resources are mocked. No network rules or VMs are created.
mock_provider "google" {}

# These existing rules have import blocks; imports need explicit test overrides.
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

run "internal_services_and_transit_are_separate" {
  command = plan

  assert {
    condition = (
      length(google_compute_firewall.allow_internal.allow) == 1 &&
      one(google_compute_firewall.allow_internal.allow).protocol == "tcp" &&
      toset(one(google_compute_firewall.allow_internal.allow).ports) == toset(["22"]) &&
      google_compute_firewall.allow_internal.source_ranges == toset(["10.0.5.0/24", "10.0.0.0/24"]) &&
      google_compute_firewall.allow_internal.target_tags == toset(["jumphost", "primary"])
    )
    error_message = "Internal SSH must remain available to jumphost and primary from team and instructor networks."
  }

  assert {
    condition = (
      length(google_compute_firewall.allow_primary_services.allow) == 2 &&
      alltrue([for rule in google_compute_firewall.allow_primary_services.allow :
        (rule.protocol == "tcp" && toset(rule.ports) == toset(["80", "6443", "8000"])) ||
        (rule.protocol == "icmp" && try(length(rule.ports), 0) == 0)
      ]) &&
      google_compute_firewall.allow_primary_services.source_ranges == toset(["10.0.5.0/24", "100.64.0.0/10"]) &&
      google_compute_firewall.allow_primary_services.target_tags == toset(["primary"]) &&
      google_compute_route.tailnet_via_jumphost.dest_range == "100.64.0.0/10"
    )
    error_message = "Primary must allow only TCP 80, 6443, 8000 and ICMP from the subnet and tailnet, with a return route for non-SNAT traffic."
  }

  assert {
    condition = (
      length(google_compute_firewall.allow_forwarded_nat.allow) == 1 &&
      one(google_compute_firewall.allow_forwarded_nat.allow).protocol == "tcp" &&
      toset(one(google_compute_firewall.allow_forwarded_nat.allow).ports) == toset(["80", "443"]) &&
      google_compute_firewall.allow_forwarded_nat.source_ranges == toset(["10.0.5.0/24"]) &&
      google_compute_firewall.allow_forwarded_nat.target_tags == toset(["jumphost"])
    )
    error_message = "NAT ingress must allow only HTTP/HTTPS from the team subnet to the jumphost."
  }

  assert {
    condition = (
      one(google_compute_firewall.allow_headscale_proxy.allow).protocol == "tcp" &&
      toset(one(google_compute_firewall.allow_headscale_proxy.allow).ports) == toset(["8080"]) &&
      google_compute_firewall.allow_headscale_proxy.source_ranges == toset(["10.0.0.2/32"]) &&
      google_compute_firewall.allow_headscale_proxy.target_tags == toset(["jumphost"])
    )
    error_message = "Only the Spectre proxy host may reach Headscale on TCP 8080."
  }

  assert {
    condition = (
      google_compute_firewall.allow_ssh_iap.source_ranges == toset(["35.235.240.0/20"]) &&
      toset(one(google_compute_firewall.allow_ssh_iap.allow).ports) == toset(["22"]) &&
      google_compute_firewall.allow_ssh_instructor.source_ranges == toset(["10.0.0.0/24"]) &&
      toset(one(google_compute_firewall.allow_ssh_instructor.allow).ports) == toset(["22"])
    )
    error_message = "Existing IAP and instructor SSH access must remain available."
  }
}

run "reject_broad_proxy_source" {
  command = plan
  variables { headscale_proxy_cidr = "10.0.0.0/24" }
  expect_failures = [var.headscale_proxy_cidr]
}

run "reject_invalid_proxy_source" {
  command = plan
  variables { headscale_proxy_cidr = "not-an-ip/32" }
  expect_failures = [var.headscale_proxy_cidr]
}
