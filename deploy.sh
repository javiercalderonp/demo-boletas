#!/usr/bin/env bash
set -euo pipefail

PROJECT="biaticos-488419"
REGION="us-central1"
BACKEND_SERVICE="viaticos-backend"
BACKOFFICE_DIR="$(cd "$(dirname "$0")" && pwd)/backoffice"
BACKOFFICE_EXTRA_ALIAS="expenseops-backoffice.vercel.app"
DEPLOY_COMMIT="$(git -C "$(dirname "$0")" rev-parse --short HEAD)"
DEPLOY_TIME="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

usage() {
  cat <<EOF
Usage: $0 [backend|front|all|logs-backend|logs-backend-tail|logs-front]

  backend            Redeploy backend to Cloud Run (build desde source)
  front              Redeploy backoffice a Vercel (producción)
  all                Ambos, backend primero
  logs-backend       Últimos 100 logs del backend (no streaming)
  logs-backend-tail  Streaming en vivo (requiere 'gcloud components install beta')
  logs-front         Logs de Vercel
EOF
}

logs_backend_read() {
  gcloud run services logs read "$BACKEND_SERVICE" \
    --region="$REGION" --project="$PROJECT" --limit=100
}

logs_backend_tail() {
  if ! gcloud beta --help >/dev/null 2>&1; then
    echo "El componente 'beta' no está instalado. Instálalo con:"
    echo "  gcloud components install beta"
    echo "O corré \"$0 logs-backend\" para últimos logs sin streaming."
    exit 1
  fi
  gcloud beta run services logs tail "$BACKEND_SERVICE" \
    --region="$REGION" --project="$PROJECT"
}

deploy_backend() {
  cd "$(dirname "$0")"
  gcloud run deploy "$BACKEND_SERVICE" \
    --source=. \
    --region="$REGION" \
    --project="$PROJECT" \
    --update-env-vars="DEPLOY_COMMIT=$DEPLOY_COMMIT,DEPLOY_TIME=$DEPLOY_TIME"
}

deploy_front() {
  cd "$BACKOFFICE_DIR"
  NEXT_PUBLIC_DEPLOY_COMMIT="$DEPLOY_COMMIT" \
    NEXT_PUBLIC_DEPLOY_TIME="$DEPLOY_TIME" \
    npm run build
  NEXT_PUBLIC_DEPLOY_COMMIT="$DEPLOY_COMMIT" \
    NEXT_PUBLIC_DEPLOY_TIME="$DEPLOY_TIME" \
    npx --yes vercel@latest build --prod --yes
  deploy_output="$(
    npx --yes vercel@latest deploy --prebuilt --prod --yes
  )"
  printf '%s\n' "$deploy_output"

  deployment_url="$(
    printf '%s\n' "$deploy_output" \
      | sed -n 's/.*"url": "\(https:\/\/[^"]*\)".*/\1/p' \
      | tail -1
  )"
  if [[ -z "$deployment_url" ]]; then
    deployment_url="$(
      printf '%s\n' "$deploy_output" \
        | sed -n 's/^Production: \(https:\/\/[^ ]*\).*/\1/p' \
        | tail -1
    )"
  fi
  if [[ -n "$deployment_url" ]]; then
    npx --yes vercel@latest alias set "$deployment_url" "$BACKOFFICE_EXTRA_ALIAS"
  else
    echo "WARNING: could not detect Vercel deployment URL for alias $BACKOFFICE_EXTRA_ALIAS" >&2
  fi
}

case "${1:-all}" in
  backend)            deploy_backend ;;
  front)              deploy_front ;;
  all)                deploy_backend && deploy_front ;;
  logs-backend)       logs_backend_read ;;
  logs-backend-tail)  logs_backend_tail ;;
  logs-front)         cd "$BACKOFFICE_DIR" && npx --yes vercel@latest logs --follow ;;
  -h|--help)          usage ;;
  *)                  usage; exit 1 ;;
esac
