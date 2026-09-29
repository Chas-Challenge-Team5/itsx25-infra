terraform {
  required_version = ">= 1.7.0, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.2"
    }
  }

  # Apply separately with an operator account, never from the infrastructure deploy job.
  backend "gcs" {
    bucket = "team5-tfstate-f7036a24"
    prefix = "terraform/monitoring-state"
  }
}

provider "google" {
  project = "itsx25-lab"
}

locals {
  project_id = "itsx25-lab"
  host       = "team5.itsx25.chas-lab.dev"
  labels     = { team = "5", service = "headscale" }

  daylight_saving = trimspace(file("${path.module}/templates/daylight-saving.promql"))
  operating_window = trimspace(templatefile("${path.module}/templates/operating-window.promql.tftpl", {
    daylight_saving = local.daylight_saving
  }))
  uptime_metric = "monitoring_googleapis_com:uptime_check_check_passed{monitored_resource=\"uptime_url\",project_id=\"${local.project_id}\",host=\"${local.host}\",check_id=\"${google_monitoring_uptime_check_config.headscale.uptime_check_id}\"}"
  uptime_query = trimspace(templatefile("${path.module}/templates/availability.promql.tftpl", {
    metric           = local.uptime_metric
    operating_window = local.operating_window
  }))
  channels = [for channel in google_monitoring_notification_channel.email : channel.name]
}

resource "google_monitoring_notification_channel" "email" {
  for_each = var.notification_emails

  project      = local.project_id
  display_name = "Team 5 operations - ${each.key}"
  type         = "email"
  enabled      = true
  labels       = { email_address = each.value }
  user_labels  = local.labels
}

resource "google_monitoring_uptime_check_config" "headscale" {
  project            = local.project_id
  display_name       = "Team 5 Headscale health"
  period             = "60s"
  timeout            = "10s"
  checker_type       = "STATIC_IP_CHECKERS"
  selected_regions   = ["EUROPE", "USA_VIRGINIA", "ASIA_PACIFIC"]
  log_check_failures = true
  user_labels        = local.labels

  monitored_resource {
    type   = "uptime_url"
    labels = { project_id = local.project_id, host = local.host }
  }

  http_check {
    request_method = "GET"
    path           = "/health"
    port           = 443
    use_ssl        = true
    validate_ssl   = true
    accepted_response_status_codes {
      status_value = 200
    }
  }

  # A generic proxy success page must not hide a failed Headscale service.
  content_matchers {
    matcher = "MATCHES_JSON_PATH"
    content = "\"pass\""
    json_path_matcher {
      json_path    = "$.status"
      json_matcher = "EXACT_MATCH"
    }
  }
}

resource "google_monitoring_alert_policy" "headscale" {
  project               = local.project_id
  display_name          = "Team 5 Headscale unavailable"
  combiner              = "OR"
  enabled               = true
  notification_channels = local.channels
  user_labels           = local.labels

  conditions {
    display_name = "Two failed locations or missing probes during operating hours"
    condition_prometheus_query_language {
      query               = local.uptime_query
      duration            = "180s"
      evaluation_interval = "60s"
    }
  }

  alert_strategy {
    auto_close           = "1800s"
    notification_prompts = ["OPENED", "CLOSED"]
  }

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      Headscale's public HTTPS /health check failed from at least two locations, or no probe samples were available in the last five minutes. The condition must persist for three minutes. A newly created check with no data can therefore alert after three minutes.

      Alerts run 08:10–24:00 Europe/Stockholm, including weekends. The VM is scheduled off 00:00–08:00; ten minutes are allowed for startup. Checks continue overnight. A failed morning start still alerts. The query implements the current EU daylight-saving rules; keep it aligned with the VM schedule.

      Check GCP VM status and serial-console output first. If reachable through IAP, inspect headscale, tailscaled, the reverse proxy, failed systemd units and /boot/efi. Avoid restarting a VM with an attached clone of its boot disk. Use the incident recovery guide before changing boot settings.

      Confirm HTTP 200 with status=pass and client connectivity after recovery. A closed incident at midnight or after missing data auto-closes is not proof of recovery. This check does not verify tailnet routing or every client.
    EOT
  }
}

# Resolve current instance IDs so an old or another team's VM cannot trigger this policy.
data "google_compute_instance" "monitored" {
  for_each = toset(["team5-jumphost", "team5-primary"])
  project  = local.project_id
  zone     = "europe-north2-b"
  name     = each.value
}

resource "google_monitoring_alert_policy" "boot_failure" {
  project               = local.project_id
  display_name          = "Team 5 emergency boot or filesystem check failure"
  combiner              = "OR"
  enabled               = true
  notification_channels = local.channels
  user_labels           = local.labels

  conditions {
    display_name = "Emergency mode or failed systemd filesystem check"
    condition_matched_log {
      filter = <<-EOT
        resource.type="gce_instance"
        resource.labels.project_id="${local.project_id}"
        resource.labels.zone="europe-north2-b"
        resource.labels.instance_id=(${join(" OR ", [for instance in data.google_compute_instance.monitored : jsonencode(instance.instance_id)])})
        log_id("journald")
        jsonPayload.MESSAGE=~"(?i)(^Reached target emergency[.]target|^Started emergency[.]service|^systemd-fsck[^:]*: Failed|^Failed to start systemd-fsck)"
      EOT
    }
  }

  alert_strategy {
    auto_close = "1800s"
    notification_rate_limit {
      period = "300s"
    }
  }

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      A Team 5 VM logged emergency mode or a failed systemd filesystem check. Inspect the matching journal entry, serial console, attached disks and /etc/fstab before rebooting. EFI must be mounted read/write before updating boot files.

      This supplemental log alert runs around the clock. It relies on the Ops Agent being able to forward the journal and may arrive late after recovery. Headscale's independent public uptime check remains the primary outage detector. Automatic closure after 30 minutes does not prove the VM recovered.
    EOT
  }
}
