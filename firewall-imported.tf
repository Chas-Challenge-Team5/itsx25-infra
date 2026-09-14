# De två reglerna skapades för hand i GCP den 9 september och låg utanför
# Terraform (#36). Båda behövs: instruktörsnätet ska nå SSH, och IAP-vägen
# används av #35 och #45. De tas därför in i koden med import-block, så
# pipelinen adopterar dem vid apply utan att någon rör GCP för hand.
# Import-blocken kan tas bort i en senare PR när adoptionen är gjord.

import {
  to = google_compute_firewall.allow_ssh_iap
  id = "projects/${var.project_id}/global/firewalls/team${var.team_id}-allow-ssh-iap"
}

resource "google_compute_firewall" "allow_ssh_iap" {
  name    = "team${var.team_id}-allow-ssh-iap"
  network = data.google_compute_network.team_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["jumphost"]
}

import {
  to = google_compute_firewall.allow_ssh_instructor
  id = "projects/${var.project_id}/global/firewalls/team${var.team_id}-allow-ssh-jumphost"
}

resource "google_compute_firewall" "allow_ssh_instructor" {
  name    = "team${var.team_id}-allow-ssh-jumphost"
  network = data.google_compute_network.team_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = [var.instructor_cidr]
  target_tags   = ["jumphost"]
}
