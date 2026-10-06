locals {
  services = [
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "aiplatform.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "cloudtrace.googleapis.com",
    "serviceusage.googleapis.com",
    "cloudresourcemanager.googleapis.com",
  ]

  runtime_roles = [
    "roles/aiplatform.user",
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
  ]
}

resource "google_project_service" "services" {
  for_each           = toset(local.services)
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# 1. Artifact Registry
resource "google_artifact_registry_repository" "repo" {
  project       = var.project_id
  location      = var.region
  repository_id = "last-call"
  description   = "Docker repository for Last Call services"
  format        = "DOCKER"
  depends_on    = [google_project_service.services]
}

# 2. Service Accounts
resource "google_service_account" "api_sa" {
  project      = var.project_id
  account_id   = "api-sa"
  display_name = "Last Call API Runtime SA"
  depends_on   = [google_project_service.services]
}

resource "google_service_account" "voice_sa" {
  project      = var.project_id
  account_id   = "voice-sa"
  display_name = "Last Call Voice Runtime SA"
  depends_on   = [google_project_service.services]
}

resource "google_service_account" "deployer_sa" {
  project      = var.project_id
  account_id   = "deployer-sa"
  display_name = "Last Call Cloud Build Deployer SA"
  depends_on   = [google_project_service.services]
}

# 3. IAM Roles on Runtime Service Accounts
resource "google_project_iam_member" "api_sa_roles" {
  for_each = toset(local.runtime_roles)
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${google_service_account.api_sa.email}"
}

resource "google_project_iam_member" "voice_sa_roles" {
  for_each = toset(local.runtime_roles)
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${google_service_account.voice_sa.email}"
}

# 4. Deployer SA permissions (Run admin, AR writer, actAs runtime SAs)
resource "google_project_iam_member" "deployer_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.deployer_sa.email}"
}

resource "google_project_iam_member" "deployer_ar_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.deployer_sa.email}"
}

resource "google_service_account_iam_member" "deployer_actas_api" {
  service_account_id = google_service_account.api_sa.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer_sa.email}"
}

resource "google_service_account_iam_member" "deployer_actas_voice" {
  service_account_id = google_service_account.voice_sa.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer_sa.email}"
}

resource "google_project_iam_member" "deployer_storage_admin" {
  project = var.project_id
  role    = "roles/storage.admin"
  member  = "serviceAccount:${google_service_account.deployer_sa.email}"
}

resource "google_project_iam_member" "deployer_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.deployer_sa.email}"
}

# Also grant Cloud Build default service account and Compute SA permissions for container builds
data "google_project" "project" {
  project_id = var.project_id
}

resource "google_project_iam_member" "compute_sa_storage" {
  project = var.project_id
  role    = "roles/storage.admin"
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
  depends_on = [google_project_service.services]
}

resource "google_project_iam_member" "compute_sa_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
  depends_on = [google_project_service.services]
}

resource "google_project_iam_member" "compute_sa_ar_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
  depends_on = [google_project_service.services]
}

resource "google_project_iam_member" "cloudbuild_ar_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
  depends_on = [google_project_service.services]
}

resource "google_project_iam_member" "cloudbuild_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
  depends_on = [google_project_service.services]
}

resource "google_service_account_iam_member" "cloudbuild_actas_api" {
  service_account_id = google_service_account.api_sa.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}

resource "google_service_account_iam_member" "cloudbuild_actas_voice" {
  service_account_id = google_service_account.voice_sa.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}

# 5. Secret Manager (container only, no secret version in terraform state)
resource "google_secret_manager_secret" "app_signing_key" {
  project   = var.project_id
  secret_id = "app-signing-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.services]
}

resource "google_secret_manager_secret_iam_member" "api_sa_secret_access" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.app_signing_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api_sa.email}"
}

# 6. Cloud Run API Service
resource "google_cloud_run_v2_service" "api" {
  project             = var.project_id
  name                = "api"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.api_sa.email
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      env {
        name = "APP_SIGNING_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.app_signing_key.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      client,
      client_version,
      template[0].containers[0].image,
      template[0].containers[0].env,
    ]
  }

  depends_on = [
    google_project_service.services,
    google_secret_manager_secret_iam_member.api_sa_secret_access
  ]
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# 7. Cloud Run Voice Service
resource "google_cloud_run_v2_service" "voice" {
  project             = var.project_id
  name                = "voice"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.voice_sa.email
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello"
    }
  }

  lifecycle {
    ignore_changes = [
      client,
      client_version,
      template[0].containers[0].image,
      template[0].containers[0].env,
    ]
  }

  depends_on = [
    google_project_service.services
  ]
}

resource "google_cloud_run_v2_service_iam_member" "voice_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.voice.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
