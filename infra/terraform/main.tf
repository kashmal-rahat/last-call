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
    "firestore.googleapis.com",
    "pubsub.googleapis.com",
    "cloudfunctions.googleapis.com",
    "eventarc.googleapis.com",
    "cloudbilling.googleapis.com",
    "places.googleapis.com",
    "storage.googleapis.com",
  ]

  runtime_roles = [
    "roles/aiplatform.user",
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
  ]

  effective_allowed_origins = var.environment == "dev" ? "${var.allowed_origins},${var.dev_allowed_origins},https://api-${data.google_project.project.number}.europe-west1.run.app,https://voice-${data.google_project.project.number}.europe-west1.run.app" : "${var.allowed_origins},https://api-${data.google_project.project.number}.europe-west1.run.app,https://voice-${data.google_project.project.number}.europe-west1.run.app"
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

resource "google_project_iam_member" "deployer_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.deployer_sa.email}"
}

# Scope deployer storage permission strictly to Cloud Build source bucket (protects tfstate)
resource "google_storage_bucket_iam_member" "deployer_build_bucket" {
  bucket = "${var.project_id}_cloudbuild"
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.deployer_sa.email}"
}

data "google_project" "project" {
  project_id = var.project_id
}

# Allow Cloud Build service agent to use deployer-sa
resource "google_service_account_iam_member" "cloudbuild_sa_token_creator" {
  service_account_id = google_service_account.deployer_sa.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-cloudbuild.iam.gserviceaccount.com"
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

resource "google_secret_manager_secret_iam_member" "voice_sa_secret_access" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.app_signing_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.voice_sa.email}"
}

resource "google_secret_manager_secret" "demo_access_code" {
  project   = var.project_id
  secret_id = "demo-access-code"
  replication {
    auto {}
  }
  depends_on = [google_project_service.services]
}

resource "google_secret_manager_secret_iam_member" "api_sa_demo_access_code" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.demo_access_code.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api_sa.email}"
}

# Phone demo (Module 9, D61/D62): Twilio account, API key and numbers as one JSON value.
# Container only: the value is added with `gcloud secrets versions add`, so Twilio
# credentials never enter Terraform state. api dials the call; voice sends WhatsApp.
resource "google_secret_manager_secret" "phone_demo_config" {
  project   = var.project_id
  secret_id = "phone-demo-config"
  replication {
    auto {}
  }
  depends_on = [google_project_service.services]
}

resource "google_secret_manager_secret_iam_member" "api_sa_phone_demo_config" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.phone_demo_config.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api_sa.email}"
}

resource "google_secret_manager_secret_iam_member" "voice_sa_phone_demo_config" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.phone_demo_config.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.voice_sa.email}"
}

# Item photos (D62): inspected shelf photos, kept one day so the agent can send the buyer a
# crop of the item. Private; served only as signed, time-limited crops through the api.
resource "google_storage_bucket" "shelf_photos" {
  project                     = var.project_id
  name                        = "${var.project_id}-shelf-photos"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true

  lifecycle_rule {
    condition {
      age = 1
    }
    action {
      type = "Delete"
    }
  }
  depends_on = [google_project_service.services]
}

resource "google_storage_bucket_iam_member" "api_sa_shelf_photos_writer" {
  bucket = google_storage_bucket.shelf_photos.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.api_sa.email}"
}

resource "google_storage_bucket_iam_member" "api_sa_shelf_photos_reader" {
  bucket = google_storage_bucket.shelf_photos.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.api_sa.email}"
}

# 6. Firestore Database & TTL
resource "google_firestore_database" "default" {
  project                 = var.project_id
  name                    = "(default)"
  location_id             = var.region
  type                    = "FIRESTORE_NATIVE"
  delete_protection_state = "DELETE_PROTECTION_ENABLED"
  deletion_policy         = "ABANDON"
  depends_on              = [google_project_service.services]
}

resource "google_firestore_field" "calls_expire_at_ttl" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "calls"
  field      = "expire_at"

  ttl_config {}
  index_config {}
}

resource "google_firestore_field" "scout_results_expire_at_ttl" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = "scout_results"
  field      = "expire_at"

  ttl_config {}
  index_config {}
}

resource "google_project_iam_member" "api_sa_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

resource "google_project_iam_member" "api_sa_serviceusage" {
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

resource "google_project_iam_member" "voice_sa_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.voice_sa.email}"
}

# 6b. Places API Quota Overrides (Module 4)
resource "google_service_usage_consumer_quota_override" "places_search_text_per_day" {
  provider       = google-beta
  project        = var.project_id
  service        = "places.googleapis.com"
  metric         = urlencode("places.googleapis.com/SearchTextRequest")
  limit          = urlencode("/d/project")
  override_value = "250"
  force          = true
  depends_on     = [google_project_service.services]
}

resource "google_service_usage_consumer_quota_override" "places_search_text_per_minute" {
  provider       = google-beta
  project        = var.project_id
  service        = "places.googleapis.com"
  metric         = urlencode("places.googleapis.com/SearchTextRequest")
  limit          = urlencode("/min/project")
  override_value = "30"
  force          = true
  depends_on     = [google_project_service.services]
}

resource "google_service_usage_consumer_quota_override" "places_search_nearby_per_day" {
  provider       = google-beta
  project        = var.project_id
  service        = "places.googleapis.com"
  metric         = urlencode("places.googleapis.com/SearchNearbyRequest")
  limit          = urlencode("/d/project")
  override_value = "250"
  force          = true
  depends_on     = [google_project_service.services]
}

resource "google_service_usage_consumer_quota_override" "places_search_nearby_per_minute" {
  provider       = google-beta
  project        = var.project_id
  service        = "places.googleapis.com"
  metric         = urlencode("places.googleapis.com/SearchNearbyRequest")
  limit          = urlencode("/min/project")
  override_value = "30"
  force          = true
  depends_on     = [google_project_service.services]
}

# 7. Cloud Run API Service
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
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "TRUE"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.google_cloud_location
      }
      env {
        name  = "GEMINI_FLASH_MODEL"
        value = var.gemini_flash_model
      }
      env {
        name  = "GEMINI_LIVE_MODEL"
        value = var.gemini_live_model
      }
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "VOICE_WS_URL"
        value = "wss://${var.voice_public_url}/ws/call"
      }
      env {
        name  = "DEMO_DAILY_SESSION_CAP"
        value = "50"
      }
      env {
        name  = "IP_RATE_LIMIT_PER_HOUR"
        value = "20"
      }
      env {
        name  = "SHELF_PHOTO_BUCKET"
        value = google_storage_bucket.shelf_photos.name
      }
      env {
        name  = "PHONE_DEMO_ENABLED"
        value = tostring(var.phone_demo_enabled)
      }
      # Attached only while the phone demo is on, so a project with it off needs no secret value.
      dynamic "env" {
        for_each = var.phone_demo_enabled ? [google_secret_manager_secret.phone_demo_config.secret_id] : []
        content {
          name = "PHONE_DEMO_CONFIG"
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }
      env {
        name = "DEMO_ACCESS_CODE"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.demo_access_code.secret_id
            version = "latest"
          }
        }
      }
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
    ]
  }

  depends_on = [
    google_project_service.services,
    google_secret_manager_secret_iam_member.api_sa_secret_access,
    google_secret_manager_secret_iam_member.api_sa_demo_access_code,
    google_secret_manager_secret_iam_member.api_sa_phone_demo_config,
    google_storage_bucket_iam_member.api_sa_shelf_photos_writer,
    google_storage_bucket_iam_member.api_sa_shelf_photos_reader,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# 8. Cloud Run Voice Service
resource "google_cloud_run_v2_service" "voice" {
  project             = var.project_id
  name                = "voice"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.voice_sa.email
    session_affinity                 = true
    timeout                          = "900s"
    max_instance_request_concurrency = 4

    scaling {
      min_instance_count = var.voice_min_instances
      max_instance_count = 2
    }
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      resources {
        cpu_idle          = false
        startup_cpu_boost = true
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "TRUE"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.google_cloud_location
      }
      env {
        name  = "GEMINI_FLASH_MODEL"
        value = var.gemini_flash_model
      }
      env {
        name  = "GEMINI_LIVE_MODEL"
        value = var.gemini_live_model
      }
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "ALLOWED_ORIGINS"
        value = local.effective_allowed_origins
      }
      env {
        name  = "MAX_CALL_SECONDS"
        value = "300"
      }
      env {
        name  = "MAX_SESSIONS_PER_INSTANCE"
        value = "4"
      }
      env {
        name  = "AGENT_VOICE"
        value = "Puck"
      }
      env {
        name  = "AGENT_GENDER"
        value = "male"
      }
      env {
        name  = "API_PUBLIC_URL"
        value = "https://${var.api_public_url}"
      }
      env {
        name  = "PHONE_DEMO_ENABLED"
        value = tostring(var.phone_demo_enabled)
      }
      dynamic "env" {
        for_each = var.phone_demo_enabled ? [google_secret_manager_secret.phone_demo_config.secret_id] : []
        content {
          name = "PHONE_DEMO_CONFIG"
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }
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
    ]
  }

  depends_on = [
    google_project_service.services,
    google_secret_manager_secret_iam_member.voice_sa_secret_access,
    google_secret_manager_secret_iam_member.voice_sa_phone_demo_config,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "voice_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.voice.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# 9. Billing Guard Infrastructure
resource "google_pubsub_topic" "budget_alerts" {
  project    = var.project_id
  name       = "budget-alerts"
  depends_on = [google_project_service.services]
}

resource "google_service_account" "billing_guard_sa" {
  project      = var.project_id
  account_id   = "billing-guard-sa"
  display_name = "Billing Guard Cloud Function SA"
  depends_on   = [google_project_service.services]
}

resource "google_project_iam_member" "billing_guard_billing_mgr" {
  project = var.project_id
  role    = "roles/billing.projectManager"
  member  = "serviceAccount:${google_service_account.billing_guard_sa.email}"
}

resource "google_project_iam_member" "billing_guard_eventarc_receiver" {
  project = var.project_id
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${google_service_account.billing_guard_sa.email}"
}

resource "google_storage_bucket" "function_source" {
  project                     = var.project_id
  name                        = "${var.project_id}-billing-guard-source"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true
  depends_on                  = [google_project_service.services]
}

resource "google_storage_bucket_iam_member" "deployer_storage_viewer" {
  bucket = google_storage_bucket.function_source.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.deployer_sa.email}"
}

resource "google_storage_bucket_iam_member" "deployer_gcf_source_viewer" {
  bucket = "gcf-v2-sources-${data.google_project.project.number}-${var.region}"
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.deployer_sa.email}"
}

data "archive_file" "billing_guard_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/billing_guard"
  output_path = "${path.module}/billing_guard.zip"
}

resource "google_storage_bucket_object" "billing_guard_code" {
  name   = "billing_guard_${data.archive_file.billing_guard_zip.output_md5}.zip"
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.billing_guard_zip.output_path
}

resource "google_cloudfunctions2_function" "billing_guard" {
  project     = var.project_id
  name        = "billing-guard"
  location    = var.region
  description = "Automated billing kill switch on budget alert"

  build_config {
    runtime         = "python312"
    entry_point     = "billing_guard"
    service_account = google_service_account.deployer_sa.id
    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.billing_guard_code.name
      }
    }
  }

  service_config {
    max_instance_count             = 1
    min_instance_count             = 0
    available_memory               = "256Mi"
    timeout_seconds                = 60
    service_account_email          = google_service_account.billing_guard_sa.email
    all_traffic_on_latest_revision = true

    environment_variables = {
      SIMULATE_DEACTIVATION = "false"
      KILL_RATIO            = "1.0"
      GCP_PROJECT           = var.project_id
    }
  }

  event_trigger {
    trigger_region        = var.region
    event_type            = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic          = google_pubsub_topic.budget_alerts.id
    retry_policy          = "RETRY_POLICY_DO_NOT_RETRY"
    service_account_email = google_service_account.billing_guard_sa.email
  }

  depends_on = [
    google_project_service.services,
    google_project_iam_member.billing_guard_billing_mgr,
    google_project_iam_member.billing_guard_eventarc_receiver,
    google_storage_bucket_iam_member.deployer_storage_viewer,
    google_storage_bucket_iam_member.deployer_gcf_source_viewer,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "billing_guard_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloudfunctions2_function.billing_guard.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.billing_guard_sa.email}"
}
