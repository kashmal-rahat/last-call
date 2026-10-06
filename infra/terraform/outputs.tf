output "artifact_registry_repo" {
  description = "Artifact Registry Docker repository URL"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}"
}

output "api_sa_email" {
  description = "API runtime service account email"
  value       = google_service_account.api_sa.email
}

output "voice_sa_email" {
  description = "Voice runtime service account email"
  value       = google_service_account.voice_sa.email
}

output "deployer_sa_email" {
  description = "Deployer service account email"
  value       = google_service_account.deployer_sa.email
}

output "api_url" {
  description = "Cloud Run API URL"
  value       = google_cloud_run_v2_service.api.uri
}

output "voice_url" {
  description = "Cloud Run Voice URL"
  value       = google_cloud_run_v2_service.voice.uri
}
