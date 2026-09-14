terraform {
  required_version = ">= 1.7.0, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }

  # Eget beständigt state, även efter merge. Appliceras separat från root/bootstrap.
  backend "gcs" {
    bucket = "team5-tfstate-f7036a24"
    prefix = "terraform/iap-access"
  }
}

provider "google" {
  project = var.project_id
}

# Kontrollera målet utan att hantera VM:ens konfiguration.
data "google_compute_instance" "jumphost" {
  project = var.project_id
  zone    = var.zone
  name    = var.instance_name
}

locals {
  # Projekt-IAM kan förvaltas med våra befintliga rättigheter.
  # IAP kontrollerar destinationen; detta är inte en bindning till VM:ens unika ID.
  iap_condition = "resource.type == 'iap.googleapis.com/TunnelInstance' && destination.ip == '${var.destination_ip}' && destination.port == 22"
}

# _member lägger till våra tilldelningar utan att ersätta andra medlemmar/roller.
resource "google_project_iam_member" "iap_ssh" {
  for_each = var.iap_users

  project = var.project_id
  role    = "roles/iap.tunnelResourceAccessor"
  member  = each.value

  condition {
    title       = "${var.instance_name}-iap-ssh"
    description = "IAP TCP forwarding to ${var.instance_name} at ${var.destination_ip}:22"
    expression  = local.iap_condition
  }

  lifecycle {
    precondition {
      condition     = data.google_compute_instance.jumphost.network_interface[0].network_ip == var.destination_ip
      error_message = "The jumphost's nic0 address does not match destination_ip. Verify the target and check for IP address reuse before changing IAM."
    }
  }
}
