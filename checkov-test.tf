resource "google_compute_firewall" "checkov_test" {
  name    = "checkov-test"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["0.0.0.0/0"]
}
