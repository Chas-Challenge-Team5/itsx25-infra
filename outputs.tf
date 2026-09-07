output "jumphost_external_ip" {
  description = "External IP of the jumphost instance"
  value       = google_compute_instance.jumphost.network_interface[0].access_config[0].nat_ip
}