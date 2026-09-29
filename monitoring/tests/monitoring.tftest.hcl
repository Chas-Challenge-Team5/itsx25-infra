mock_provider "google" {}

variables {
  notification_emails = {
    one   = "one@example.org"
    two   = "two@example.org"
    three = "three@example.org"
    four  = "four@example.org"
    five  = "five@example.org"
  }
}

run "monitoring_contract" {
  # All resources/data are mocked; no API calls or real infrastructure changes.
  command = apply

  assert {
    condition = (
      length(google_monitoring_notification_channel.email) == 5 &&
      alltrue([for alias, channel in google_monitoring_notification_channel.email :
        channel.type == "email" && channel.enabled && channel.labels.email_address == var.notification_emails[alias]
      ]) &&
      toset(google_monitoring_alert_policy.headscale.notification_channels) == toset(local.channels) &&
      toset(google_monitoring_alert_policy.boot_failure.notification_channels) == toset(local.channels)
    )
    error_message = "Both policies must notify every configured recipient."
  }

  assert {
    condition = (
      google_monitoring_uptime_check_config.headscale.monitored_resource[0].labels.host == "team5.itsx25.chas-lab.dev" &&
      google_monitoring_uptime_check_config.headscale.http_check[0].path == "/health" &&
      google_monitoring_uptime_check_config.headscale.http_check[0].use_ssl &&
      google_monitoring_uptime_check_config.headscale.http_check[0].validate_ssl &&
      one(google_monitoring_uptime_check_config.headscale.http_check[0].accepted_response_status_codes).status_value == 200 &&
      google_monitoring_uptime_check_config.headscale.content_matchers[0].content == "\"pass\"" &&
      google_monitoring_uptime_check_config.headscale.content_matchers[0].json_path_matcher[0].json_path == "$.status" &&
      length(google_monitoring_uptime_check_config.headscale.selected_regions) == 3 &&
      google_monitoring_uptime_check_config.headscale.period == "60s"
    )
    error_message = "Require public HTTPS, a valid certificate, exact HTTP 200 and Headscale's health payload from three locations."
  }

  assert {
    condition = (
      google_monitoring_alert_policy.headscale.conditions[0].condition_prometheus_query_language[0].duration == "180s" &&
      strcontains(local.uptime_query, google_monitoring_uptime_check_config.headscale.uptime_check_id) &&
      strcontains(local.uptime_query, "project_id=\"itsx25-lab\"") &&
      strcontains(local.uptime_query, "host=\"team5.itsx25.chas-lab.dev\"") &&
      toset(google_monitoring_alert_policy.headscale.alert_strategy[0].notification_prompts) == toset(["OPENED", "CLOSED"])
    )
    error_message = "Alert only on this check, tolerate brief failures and send recovery notifications."
  }

  assert {
    condition = (
      alltrue([for instance in data.google_compute_instance.monitored :
        strcontains(google_monitoring_alert_policy.boot_failure.conditions[0].condition_matched_log[0].filter, instance.instance_id)
      ]) &&
      toset(keys(data.google_compute_instance.monitored)) == toset(["team5-jumphost", "team5-primary"]) &&
      strcontains(google_monitoring_alert_policy.boot_failure.conditions[0].condition_matched_log[0].filter, "log_id(\"journald\")") &&
      google_monitoring_alert_policy.boot_failure.alert_strategy[0].notification_rate_limit[0].period == "300s"
    )
    error_message = "Limit the supplemental journal alert to the two Team 5 VM IDs and rate-limit notifications."
  }
}

run "reject_empty_recipients" {
  command = plan
  variables { notification_emails = {} }
  expect_failures = [var.notification_emails]
}

run "reject_invalid_email" {
  command = plan
  variables { notification_emails = { member = "not-an-email" } }
  expect_failures = [var.notification_emails]
}
