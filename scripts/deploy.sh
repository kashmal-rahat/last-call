#!/usr/bin/env bash
set -euo pipefail

SERVICE="${1:-}"
if [[ "$SERVICE" != "api" && "$SERVICE" != "voice" ]]; then
  echo "Usage: $0 <api|voice>"
  exit 1
fi

PROJECT_ID="${GCP_PROJECT:-kayrox-last-call}"
REGION="${GCP_REGION:-europe-west1}"
REPO="${REGION}-docker.pkg.dev/${PROJECT_ID}/last-call"
COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo 'manual')"
IMAGE="${REPO}/${SERVICE}:${COMMIT_SHA}"

echo "=================================================="
echo "Deploying ${SERVICE} to Cloud Run"
echo "Project:  ${PROJECT_ID}"
echo "Region:   ${REGION}"
echo "Image:    ${IMAGE}"
echo "=================================================="

# 1. Build and push image using Cloud Build from repo root
TMP_CONFIG=$(mktemp)
cat <<EOF > "${TMP_CONFIG}"
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '${IMAGE}', '-f', 'services/${SERVICE}/Dockerfile', '.']
images:
  - '${IMAGE}'
options:
  logging: 'CLOUD_LOGGING_ONLY'
EOF

echo "--> Submitting build to Google Cloud Build using deployer-sa..."
gcloud builds submit . \
  --project="${PROJECT_ID}" \
  --service-account="projects/${PROJECT_ID}/serviceAccounts/deployer-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --config="${TMP_CONFIG}"
rm -f "${TMP_CONFIG}"

# 2. Deploy to Cloud Run
echo "--> Deploying image to Cloud Run service '${SERVICE}'..."
gcloud run deploy "${SERVICE}" \
  --image="${IMAGE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --service-account="${SERVICE}-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --update-env-vars="GIT_COMMIT=${COMMIT_SHA},ENVIRONMENT=production" \
  --quiet

SERVICE_URL=$(gcloud run services describe "${SERVICE}" --project="${PROJECT_ID}" --region="${REGION}" --format='value(status.url)')
echo "--> Successfully deployed ${SERVICE} to: ${SERVICE_URL}"
echo "--> Verifying health endpoint: ${SERVICE_URL}/health"
curl -fsS "${SERVICE_URL}/health"
echo ""
