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

variable "gemini_flash_region" {
  description = "Vertex AI location for Gemini Flash"
  type        = string
  default     = "eu"
}

variable "gemini_live_model" {
  description = "Gemini Live model name"
  type        = string
  default     = "gemini-3.8-live"
}

variable "gemini_live_region" {
  description = "Vertex AI location for Gemini Live"
  type        = string
  default     = "eu"
}
