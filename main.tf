terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  instructor_vpc_self_link = "https://www.googleapis.com/compute/v1/projects/${var.project_id}/global/networks/instructor-vpc"
  team_zone                = (var.team_id - 1) % 3
  jumphost_zone            = coalesce(var.jumphost_zone, data.google_compute_zones.available.names[local.team_zone])
  primary_zone             = coalesce(var.primary_zone, data.google_compute_zones.available.names[local.team_zone])
  subnet_cidr              = "10.0.${var.team_id}.0/24"
}

data "google_compute_zones" "available" {
  region = var.region
}

data "google_compute_network" "team_vpc" {
  name = "team${var.team_id}-vpc"
}

resource "google_compute_subnetwork" "team" {
  name                     = "team${var.team_id}-subnet"
  ip_cidr_range            = local.subnet_cidr
  region                   = var.region
  network                  = data.google_compute_network.team_vpc.id
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_address" "jumphost" {
  name   = "team${var.team_id}-jumphost-ip"
  region = var.region
}

resource "google_compute_route" "internet_via_jumphost" {
  name              = "team${var.team_id}-internet-via-jumphost"
  network           = data.google_compute_network.team_vpc.id
  dest_range        = "0.0.0.0/0"
  priority          = 800
  next_hop_instance = google_compute_instance.jumphost.self_link
  tags              = ["no-external-ip"]
}

resource "google_compute_route" "tailnet_via_jumphost" {
  name              = "team${var.team_id}-tailnet-via-jumphost"
  network           = data.google_compute_network.team_vpc.id
  dest_range        = "100.64.0.0/10"
  priority          = 800
  next_hop_instance = google_compute_instance.jumphost.self_link
  tags              = ["no-external-ip"]
}

resource "google_compute_resource_policy" "daily_schedule" {
  name   = "team${var.team_id}-daily-schedule"
  region = var.region

  instance_schedule_policy {
    time_zone = "Europe/Stockholm"
    vm_start_schedule {
      schedule = "0 8 * * *"
    }
    vm_stop_schedule {
      schedule = "0 0 * * *"
    }
  }
}

resource "google_compute_instance" "jumphost" {
  name         = "team${var.team_id}-jumphost"
  machine_type = "e2-micro"
  zone         = local.jumphost_zone

  allow_stopping_for_update = true
  can_ip_forward            = true

  tags = ["jumphost"]

  resource_policies = [google_compute_resource_policy.daily_schedule.id]

  boot_disk {
    initialize_params {
      image = "${var.project_id}/debian"
      size  = 20
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.team.id
    network_ip = cidrhost(local.subnet_cidr, 2)
    access_config {
      nat_ip = google_compute_address.jumphost.address
    }
  }

  metadata = {
    ssh-keys               = join("\n", [for user in var.ssh_users : "${user.username}:${user.public_key}"])
    block-project-ssh-keys = true
    startup-script         = <<-EOT
      #!/bin/bash
      set -e

      if ! swapon --show | grep -q "/swapfile"; then
        fallocate -l 1G /swapfile
        chmod 600 /swapfile
        mkswap /swapfile
        swapon /swapfile
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
      fi

      echo 'vm.swappiness=20' > /etc/sysctl.d/01-swappiness.conf
      echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-ip-forward.conf
      DEFAULT_IF=$(ip ro sh default | awk '/default/ {print $5}')
      # Own chains separate local services from forwarded client traffic.
      # Restore only these chains; leave other host firewall rules intact.
      cat > /usr/local/sbin/team-nat-firewall <<'SCRIPT'
      #!/bin/bash
      set -e
      iptables-restore --noflush <<'RULES'
      *filter
      :TEAM-NAT-INPUT - [0:0]
      :TEAM-NAT-FORWARD - [0:0]
      -F TEAM-NAT-INPUT
      -F TEAM-NAT-FORWARD
      -A TEAM-NAT-INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
      -A TEAM-NAT-INPUT -s ${local.subnet_cidr} -p tcp -m multiport --dports 80,443 -j DROP
      -A TEAM-NAT-INPUT -j RETURN
      -A TEAM-NAT-FORWARD -m conntrack --ctstate INVALID -j DROP
      -A TEAM-NAT-FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
      -A TEAM-NAT-FORWARD -s ${local.subnet_cidr} -p tcp -m multiport --dports 80,443 -m conntrack --ctstate NEW -j ACCEPT
      -A TEAM-NAT-FORWARD -j DROP
      COMMIT
      RULES
      iptables -C INPUT -j TEAM-NAT-INPUT 2>/dev/null || iptables -I INPUT 1 -j TEAM-NAT-INPUT
      iptables -C FORWARD -j TEAM-NAT-FORWARD 2>/dev/null || iptables -I FORWARD 1 -j TEAM-NAT-FORWARD
      SCRIPT
      chmod 750 /usr/local/sbin/team-nat-firewall
      cat > /etc/systemd/system/team-nat-firewall.service <<'UNIT'
      [Unit]
      Description=Filter local and forwarded jumphost traffic
      DefaultDependencies=no
      After=local-fs.target
      Before=network-pre.target
      Wants=network-pre.target

      [Service]
      Type=oneshot
      ExecStart=/usr/local/sbin/team-nat-firewall
      RemainAfterExit=yes

      [Install]
      WantedBy=multi-user.target
      UNIT
      systemctl daemon-reload
      systemctl enable team-nat-firewall.service
      systemctl restart team-nat-firewall.service

      # Install filtering before enabling forwarding. Avoid duplicate NAT rules.
      iptables -t nat -C POSTROUTING -o "$DEFAULT_IF" -s "${local.subnet_cidr}" -j MASQUERADE 2>/dev/null || \
        iptables -t nat -A POSTROUTING -o "$DEFAULT_IF" -s "${local.subnet_cidr}" -j MASQUERADE
      sysctl --system
    EOT
  }
}

# resource "google_compute_instance" "primary" {
#   name         = "team${var.team_id}-primary"
#   machine_type = "e2-small"
#   zone         = local.primary_zone

#   allow_stopping_for_update = true

#   tags = ["primary", "no-external-ip"]

#   resource_policies = [google_compute_resource_policy.daily_schedule.id]

#   boot_disk {
#     initialize_params {
#       image = "${var.project_id}/debian"
#       size  = 20
#     }
#   }

#   network_interface {
#     subnetwork = google_compute_subnetwork.team.id
#     network_ip = cidrhost(local.subnet_cidr, 3)
#   }

#   metadata = {
#     ssh-keys               = join("\n", [for user in var.ssh_users : "${user.username}:${user.public_key}"])
#     block-project-ssh-keys = true
#     startup-script         = <<-EOT
#       #!/bin/bash
#       set -e

#       if ! swapon --show | grep -q "/swapfile"; then
#         fallocate -l 1G /swapfile
#         chmod 600 /swapfile
#         mkswap /swapfile
#         swapon /swapfile
#         echo '/swapfile none swap sw 0 0' >> /etc/fstab
#       fi

#       echo 'vm.swappiness=20' > /etc/sysctl.d/01-swappiness.conf
#       sysctl --system
#     EOT
#   }
# }

resource "google_compute_firewall" "allow_ssh" {
  name    = "team${var.team_id}-allow-ssh"
  network = data.google_compute_network.team_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = var.ssh_source_ranges
  target_tags   = ["jumphost"]
}

resource "google_compute_firewall" "allow_internal" {
  name    = "team${var.team_id}-allow-internal"
  network = data.google_compute_network.team_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = [var.instructor_cidr, local.subnet_cidr]
  target_tags   = ["jumphost"]
}


resource "google_compute_firewall" "allow_forwarded_nat" {
  name    = "team${var.team_id}-allow-forwarded-nat"
  network = data.google_compute_network.team_vpc.name

  allow {
    protocol = "tcp"

    ports = ["80", "443"]
  }
  # GCP also admits these ports to the host; TEAM-NAT-INPUT blocks that path.
  source_ranges = [local.subnet_cidr]
  target_tags   = ["jumphost"]
}
