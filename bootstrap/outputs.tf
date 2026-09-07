output "bucket_name" {
  description = "The name of the created GCS bucket for Terraform state storage"
  value       = google_storage_bucket.terraform_state.name
}

output "cicd_service_account_key_json" {
  description = "The JSON key for the CI/CD service account"
  value       = google_service_account_key.cicd.private_key
  sensitive   = true
}
