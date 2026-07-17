#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-biaticos-488419}"
REGION="${REGION:-us-central1}"
BACKEND_SERVICE="${BACKEND_SERVICE:-viaticos-backend}"
BACKOFFICE_SERVICE="${BACKOFFICE_SERVICE:-viaticos-backoffice}"
BUCKET_NAME="${GCS_BUCKET_NAME:-${PROJECT_ID}-expense-documents}"
BACKEND_SA="${BACKEND_SA:-expense-backend-runtime}"
SCHEDULER_SA="${SCHEDULER_SA:-expense-scheduler-invoker}"
SCHEDULER_JOB="${SCHEDULER_JOB:-viaticos-reminders}"
SCHEDULER_CRON="${SCHEDULER_CRON:-*/10 * * * *}"
SCHEDULER_TIME_ZONE="${SCHEDULER_TIME_ZONE:-America/Santiago}"

required_commands=(gcloud)
for cmd in "${required_commands[@]}"; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
done

gcloud config set project "$PROJECT_ID" >/dev/null

echo "Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudscheduler.googleapis.com \
  documentai.googleapis.com \
  storage.googleapis.com \
  --project="$PROJECT_ID"

ensure_service_account() {
  local name="$1"
  local display_name="$2"
  if gcloud iam service-accounts describe "${name}@${PROJECT_ID}.iam.gserviceaccount.com" \
    --project="$PROJECT_ID" >/dev/null 2>&1; then
    echo "Service account exists: $name"
    return
  fi
  gcloud iam service-accounts create "$name" \
    --project="$PROJECT_ID" \
    --display-name="$display_name"
}

ensure_service_account "$BACKEND_SA" "Expense backend runtime"
ensure_service_account "$SCHEDULER_SA" "Expense scheduler invoker"

echo "Ensuring private documents bucket..."
if ! gcloud storage buckets describe "gs://${BUCKET_NAME}" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${BUCKET_NAME}" \
    --project="$PROJECT_ID" \
    --location="$REGION" \
    --uniform-bucket-level-access
fi

BACKEND_SA_EMAIL="${BACKEND_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_SA_EMAIL="${SCHEDULER_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Granting minimum IAM..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${BACKEND_SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" \
  --quiet >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${BACKEND_SA_EMAIL}" \
  --role="roles/documentai.apiUser" \
  --quiet >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
  --member="serviceAccount:${BACKEND_SA_EMAIL}" \
  --role="roles/storage.objectAdmin" \
  --quiet >/dev/null

echo "Creating placeholder secrets if missing..."
secret_names=(
  backoffice-auth-secret
  backoffice-default-admin-email
  backoffice-default-admin-password
  meta-access-token
  meta-app-secret
  meta-verify-token
  openai-api-key
  scheduler-endpoint-token
  docusign-integration-key
  docusign-secret-key
  docusign-refresh-token
)
for secret_name in "${secret_names[@]}"; do
  if gcloud secrets describe "$secret_name" --project="$PROJECT_ID" >/dev/null 2>&1; then
    echo "Secret exists: $secret_name"
    continue
  fi
  printf 'REPLACE_ME\n' | gcloud secrets create "$secret_name" \
    --project="$PROJECT_ID" \
    --replication-policy=automatic \
    --data-file=-
done

echo "Deploy commands prepared:"
cat <<EOF
gcloud run deploy ${BACKEND_SERVICE} \\
  --source=. \\
  --region=${REGION} \\
  --project=${PROJECT_ID} \\
  --service-account=${BACKEND_SA_EMAIL} \\
  --min-instances=1 \\
  --set-env-vars=APP_ENV=prod,DEBUG=false,LOG_FORMAT=json,PERSISTENCE_BACKEND=sqlite,SQLITE_DATABASE_PATH=/tmp/expense_agent.sqlite3,GCS_BUCKET_NAME=${BUCKET_NAME}

gcloud scheduler jobs create http ${SCHEDULER_JOB} \\
  --project=${PROJECT_ID} \\
  --location=${REGION} \\
  --schedule="${SCHEDULER_CRON}" \\
  --time-zone="${SCHEDULER_TIME_ZONE}" \\
  --uri="https://<backend-url>/jobs/reminders/run" \\
  --http-method=POST \\
  --oidc-service-account-email=${SCHEDULER_SA_EMAIL} \\
  --headers="X-Scheduler-Token=<scheduler-token>"
EOF

echo "Bootstrap complete. Replace placeholder secrets before production traffic."
