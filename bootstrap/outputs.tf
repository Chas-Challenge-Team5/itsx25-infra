output "bucket_name" {
  description = "The name of the created GCS bucket for Terraform state storage"
  value       = google_storage_bucket.terraform_state.name
}

output "cicd_service_account_email" {
  description = "The email of the CI/CD service account"
  value       = google_service_account.cicd.email
}

output "workload_identity_provider" {
  description = "The full resource name of the Workload Identity Provider"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "cicd_service_account_key_json" {
  description = "The JSON key for the CI/CD service account (fallback, not used by WIF)"
  value       = google_service_account_key.cicd.private_key
  sensitive   = true
}
