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

# Headscale-datan finns bara på jumphostens disk (#85).
run "jumphost_is_protected_and_backed_up" {
  command = plan

  assert {
    condition     = google_compute_instance.jumphost.deletion_protection == true
    error_message = "The jumphost must have deletion protection, since it holds the only copy of the Headscale data."
  }

  assert {
    condition = (
      google_compute_resource_policy.jumphost_snapshots.name == "team5-jumphost-snapshots" &&
      google_compute_resource_policy.jumphost_snapshots.region == "europe-north2" &&
      google_compute_resource_policy.jumphost_snapshots.snapshot_schedule_policy[0].schedule[0].daily_schedule[0].days_in_cycle == 1 &&
      google_compute_resource_policy.jumphost_snapshots.snapshot_schedule_policy[0].schedule[0].daily_schedule[0].start_time == "03:00"
    )
    error_message = "The jumphost disk must be snapshotted daily at 03:00 UTC, while the VM is stopped."
  }

  assert {
    condition = (
      google_compute_resource_policy.jumphost_snapshots.snapshot_schedule_policy[0].retention_policy[0].max_retention_days == 7 &&
      google_compute_resource_policy.jumphost_snapshots.snapshot_schedule_policy[0].retention_policy[0].on_source_disk_delete == "KEEP_AUTO_SNAPSHOTS" &&
      google_compute_resource_policy.jumphost_snapshots.snapshot_schedule_policy[0].snapshot_properties[0].storage_locations == toset(["eu"])
    )
    error_message = "Snapshots must be kept for 7 days in the EU and survive deletion of the disk."
  }

  assert {
    condition = (
      google_compute_disk_resource_policy_attachment.jumphost_snapshots.name == "team5-jumphost-snapshots" &&
      google_compute_disk_resource_policy_attachment.jumphost_snapshots.zone == "europe-north2-b"
    )
    error_message = "The snapshot schedule must be attached to the jumphost disk in the jumphost's zone."
  }
}
