terraform {
  required_version = ">= 1.7.0, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.2"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  team_zone     = (var.team_id - 1) % 3
  jumphost_zone = coalesce(var.jumphost_zone, data.google_compute_zones.available.names[local.team_zone])
  primary_zone  = coalesce(var.primary_zone, data.google_compute_zones.available.names[local.team_zone])
  subnet_cidr   = "10.0.${var.team_id}.0/24"
  tailnet_cidr  = "100.64.0.0/10"
  nat_tcp_ports = ["80", "443"]
  # Spectre är samma värd som Headscale-proxyn (#51).
  spectre_cidr = var.headscale_proxy_cidr
  nat_firewall_script = templatefile("${path.module}/templates/team-nat-firewall.sh.tftpl", {
    subnet_cidr   = local.subnet_cidr
    nat_tcp_ports = join(",", local.nat_tcp_ports)
    tailnet_cidr  = local.tailnet_cidr
    spectre_cidr  = local.spectre_cidr
  })
  # Svarar bara på tailnätet och bara för labbzonen, som Split DNS skickar hit.
  dnsmasq_config = <<-EOT
    interface=tailscale0
    bind-dynamic
    no-resolv
    no-hosts
    server=/${var.lab_dns_zone}/169.254.169.254
  EOT
  host_hardening_script = templatefile("${path.module}/templates/team-host-hardening.sh.tftpl", {
    sshd_config     = filebase64("${path.module}/templates/sshd-team5.conf")
    resolved_config = filebase64("${path.module}/templates/resolved-team5.conf")
  })
  ops_agent_script = templatefile("${path.module}/templates/team-ops-agent.sh.tftpl", {
    config = filebase64("${path.module}/templates/ops-agent-config.yaml")
  })
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
  dest_range        = local.tailnet_cidr
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
  # checkov:skip=CKV_GCP_40:Jumphost är teamets avsedda internet-gateway och måste ha publik IP
  # checkov:skip=CKV_GCP_36:IP forwarding krävs för NAT/routning till primary och Spectre (#50)
  # checkov:skip=CKV_GCP_38:CSEK skulle kräva manuell nyckel vid varje boot, inte lämpligt för labbmiljön
  name         = "team${var.team_id}-jumphost"
  machine_type = "e2-micro"
  zone         = local.jumphost_zone

  allow_stopping_for_update = true
  can_ip_forward            = true

  # Headscale-datan finns bara på den här disken (#85). prevent_destroy stoppar
  # en ersättning redan i planen, deletion_protection stoppar en radering i GCP
  # som görs utanför Terraform.
  deletion_protection = true

  lifecycle {
    prevent_destroy = true
  }

  tags = ["jumphost"]

  resource_policies = [google_compute_resource_policy.daily_schedule.id]

  # Kontot har ingen roll i projektet, bara secretAccessor på instructor-demo-secret.
  # Byte av konto eller scopes stoppar och startar VM:n.
  service_account {
    email  = "team${var.team_id}-jumphost@${var.project_id}.iam.gserviceaccount.com"
    scopes = ["cloud-platform"]
  }

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
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = true
    startup-script         = <<-EOT
      #!/bin/bash
      set -e

      # Härdning av sshd och resolved (#86). Körs först så att ett senare fel inte
      # hoppar över den, och ett fel här stoppar inte resten av scriptet.
      echo '${base64encode(local.host_hardening_script)}' | base64 --decode > /usr/local/sbin/team-host-hardening
      chmod 750 /usr/local/sbin/team-host-hardening
      /usr/local/sbin/team-host-hardening || echo 'team-host-hardening failed; see the lines above.' >&2

      # Systemjournalen till Cloud Logging (#92). En gång installerad startar
      # agenten själv vid boot, även om apt inte når ut just då.
      echo '${base64encode(local.ops_agent_script)}' | base64 --decode > /usr/local/sbin/team-ops-agent
      chmod 750 /usr/local/sbin/team-ops-agent
      /usr/local/sbin/team-ops-agent || echo 'team-ops-agent failed; see the lines above.' >&2

      if ! swapon --show | grep -q "/swapfile"; then
        fallocate -l 1G /swapfile
        chmod 600 /swapfile
        mkswap /swapfile
        swapon /swapfile
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
      fi

      echo 'vm.swappiness=20' > /etc/sysctl.d/01-swappiness.conf
      echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-ip-forward.conf
      # Encode the exact tested helper so nested heredoc indentation cannot corrupt it.
      echo '${base64encode(local.nat_firewall_script)}' | base64 --decode > /usr/local/sbin/team-nat-firewall
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

      /usr/local/sbin/team-nat-firewall --enable-forwarding
      sysctl --system

      # DNS-proxy för Split DNS (#51). Konfigurationen skrivs före installationen,
      # så att paketets standardinställning aldrig lyssnar på alla gränssnitt.
      mkdir -p /etc/dnsmasq.d
      echo '${base64encode(local.dnsmasq_config)}' | base64 --decode > /etc/dnsmasq.d/tailscale-split-dns.conf
      if ! dpkg-query -W -f='$${Status}' dnsmasq 2>/dev/null | grep -q 'install ok installed'; then
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends dnsmasq
      fi
      systemctl enable dnsmasq.service
      systemctl restart dnsmasq.service
    EOT
  }

  shielded_instance_config {
    enable_secure_boot          = var.enable_secure_boot
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
}

# Daglig snapshot av jumphostens disk med Headscale-datan (#85). GCP tar den inom
# fyra timmar från starttiden. 01:00-05:00 UTC ligger inom daily_schedule-stoppet
# både sommar- och vintertid, så Headscale är nedstängd och databasen konsekvent.
# Snapshots behålls när disken raderas, annars försvinner backupen med den.
resource "google_compute_resource_policy" "jumphost_snapshots" {
  name   = "team${var.team_id}-jumphost-snapshots"
  region = var.region

  snapshot_schedule_policy {
    schedule {
      daily_schedule {
        days_in_cycle = 1
        start_time    = "01:00"
      }
    }

    retention_policy {
      max_retention_days    = 7
      on_source_disk_delete = "KEEP_AUTO_SNAPSHOTS"
    }

    snapshot_properties {
      storage_locations = ["eu"]
      labels = {
        team    = "team${var.team_id}"
        purpose = "headscale-backup"
      }
    }
  }
}

# Disknamnet tas från instansens källa, så att en ny disk får schemat igen.
resource "google_compute_disk_resource_policy_attachment" "jumphost_snapshots" {
  name = google_compute_resource_policy.jumphost_snapshots.name
  disk = reverse(split("/", google_compute_instance.jumphost.boot_disk[0].source))[0]
  zone = google_compute_instance.jumphost.zone

  # En policy som används går inte att radera. Kopplingen tas bort först när
  # schemat ändras, eftersom policyn då ersätts under samma namn.
  lifecycle {
    replace_triggered_by = [google_compute_resource_policy.jumphost_snapshots]
  }
}

resource "google_compute_instance" "primary" {
  # checkov:skip=CKV_GCP_38:CSEK skulle kräva manuell nyckel vid varje boot, inte lämpligt för labbmiljön
  name         = "team${var.team_id}-primary"
  machine_type = "e2-small" # k3s behöver mer än 1 GB minne (#108)
  zone         = local.primary_zone

  allow_stopping_for_update = true

  tags = ["primary", "no-external-ip"]

  resource_policies = [google_compute_resource_policy.daily_schedule.id]

  # Kontot får bara skriva loggar (#92), och scopet begränsar token till det.
  # OS Login kräver serviceAccountUser på kontot, som delas ut i access/.
  # Byte av konto eller scopes stoppar och startar VM:n.
  service_account {
    email  = "team${var.team_id}-primary@${var.project_id}.iam.gserviceaccount.com"
    scopes = ["https://www.googleapis.com/auth/logging.write"]
  }

  boot_disk {
    initialize_params {
      image = "${var.project_id}/debian"
      size  = 20
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.team.id
    network_ip = cidrhost(local.subnet_cidr, 3)
  }

  metadata = {
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = true
    startup-script         = <<-EOT
      #!/bin/bash
      set -e

      # Härdning av sshd och resolved (#86). Körs först så att ett senare fel inte
      # hoppar över den, och ett fel här stoppar inte resten av scriptet.
      echo '${base64encode(local.host_hardening_script)}' | base64 --decode > /usr/local/sbin/team-host-hardening
      chmod 750 /usr/local/sbin/team-host-hardening
      /usr/local/sbin/team-host-hardening || echo 'team-host-hardening failed; see the lines above.' >&2

      # Systemjournalen till Cloud Logging (#92). En gång installerad startar
      # agenten själv vid boot, även om apt inte når ut just då.
      echo '${base64encode(local.ops_agent_script)}' | base64 --decode > /usr/local/sbin/team-ops-agent
      chmod 750 /usr/local/sbin/team-ops-agent
      /usr/local/sbin/team-ops-agent || echo 'team-ops-agent failed; see the lines above.' >&2

      if ! swapon --show | grep -q "/swapfile"; then
        fallocate -l 1G /swapfile
        chmod 600 /swapfile
        mkswap /swapfile
        swapon /swapfile
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
      fi

      echo 'vm.swappiness=20' > /etc/sysctl.d/01-swappiness.conf
      sysctl --system
    EOT
  }

  # Den befintliga disken kör den signerade kärnan sedan #79. Labbimagen har
  # fortfarande den osignerade, så en ny primary startar inte med Secure Boot
  # (#63). Byts instansen måste kärnan bytas med Secure Boot av först.
  shielded_instance_config {
    enable_secure_boot          = var.enable_secure_boot
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
}

resource "google_compute_firewall" "allow_internal" {
  name    = "team${var.team_id}-allow-internal"
  network = data.google_compute_network.team_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = [var.instructor_cidr, local.subnet_cidr]
  target_tags   = ["jumphost", "primary"]
}

# Workshop #50: support both subnet SNAT and preserved tailnet source addresses.
# 80 är appen och 6443 k3s API för CI-runnern (#108). Headscale-policyn avgör vem som når vilken port.
resource "google_compute_firewall" "allow_primary_services" {
  name    = "team${var.team_id}-allow-primary-services"
  network = data.google_compute_network.team_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["80", "6443", "8000"]
  }

  allow {
    protocol = "icmp"
  }

  source_ranges = [local.subnet_cidr, local.tailnet_cidr]
  target_tags   = ["primary"]
}

resource "google_compute_firewall" "allow_forwarded_nat" {
  name    = "team${var.team_id}-allow-forwarded-nat"
  network = data.google_compute_network.team_vpc.name

  allow {
    protocol = "tcp"

    ports = local.nat_tcp_ports
  }
  # GCP also admits these ports to the host; TEAM-NAT-INPUT blocks that path.
  source_ranges = [local.subnet_cidr]
  target_tags   = ["jumphost"]
}

# Preserve the instructor proxy's Headscale access when the broad rule is removed (#48).
resource "google_compute_firewall" "allow_headscale_proxy" {
  name    = "team${var.team_id}-allow-headscale-proxy"
  network = data.google_compute_network.team_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["8080"]
  }

  source_ranges = [var.headscale_proxy_cidr]
  target_tags   = ["jumphost"]
}
