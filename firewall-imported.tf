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
