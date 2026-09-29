output "uptime_check_id" {
  description = "Identifier used to find the Headscale uptime check."
  value       = google_monitoring_uptime_check_config.headscale.uptime_check_id
}

output "alert_policy_names" {
  description = "Managed policies; use these to inspect incidents after the approved delivery test."
  value = {
    headscale    = google_monitoring_alert_policy.headscale.name
    boot_failure = google_monitoring_alert_policy.boot_failure.name
  }
}
