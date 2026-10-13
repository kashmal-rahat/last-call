variable "project_id" {
  description = "The GCP project ID"
  type        = string
  default     = "kayrox-last-call"
}

variable "region" {
  description = "The default GCP region"
  type        = string
  default     = "europe-west1"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
}

variable "gemini_flash_model" {
  description = "Gemini Flash model name"
  type        = string
  default     = "gemini-3.8-flash"
}

variable "gemini_live_model" {
  description = "Gemini Live model name"
  type        = string
  default     = "gemini-3.8-live"
}

variable "google_cloud_location" {
  description = "Vertex AI location endpoint for Gemini models"
  type        = string
  default     = "eu"
}

variable "voice_min_instances" {
  description = "Minimum instances for voice service (0 for dev, 1 for judging window)"
  type        = number
  default     = 0
}

variable "api_public_url" {
  description = "Public domain / host for api service"
  type        = string
  default     = "api-cujkm3kt5q-ew.a.run.app"
}

variable "voice_public_url" {
  description = "Public domain / host for voice service"
  type        = string
  default     = "voice-cujkm3kt5q-ew.a.run.app"
}

variable "allowed_origins" {
  description = "Allowed CORS and WebSocket origins for production"
  type        = string
  default     = "https://api-cujkm3kt5q-ew.a.run.app,https://voice-cujkm3kt5q-ew.a.run.app"
}

variable "dev_allowed_origins" {
  description = "Additional allowed origins for development"
  type        = string
  default     = "http://localhost:8080,http://localhost:8000"
}




variable "phone_demo_enabled" {
  description = "Phone demo (Module 9, D61): Twilio rings the presenter's own SIM for the demo video. Keep false for judging; the phone-demo-config secret needs a version before setting true."
  type        = bool
  default     = false
}
