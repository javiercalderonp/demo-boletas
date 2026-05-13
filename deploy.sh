#!/usr/bin/env bash
set -euo pipefail

PROJECT="biaticos-488419"
REGION="us-central1"
BACKEND_SERVICE="viaticos-backend"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKOFFICE_DIR="$ROOT_DIR/backoffice"
BACKOFFICE_EXTRA_ALIAS="expenseops-backoffice.vercel.app"
DEPLOY_COMMIT=""
DEPLOY_TIME=""

usage() {
  cat <<EOF
Usage: $0 [backend|front|all|logs-backend|logs-backend-tail|logs-front]

  backend            Redeploy backend to Cloud Run (build desde source)
  front              Redeploy backoffice a Vercel (producción)
  all                Ambos, backend primero
  logs-backend       Últimos 100 logs del backend (no streaming)
  logs-backend-tail  Streaming en vivo (requiere 'gcloud components install beta')
  logs-front         Logs de Vercel

Environment overrides:
  SKIP_REPO_SYNC=1          No hace git fetch/pull antes de deploy
  ALLOW_DIRTY_DEPLOY=1      Permite deploy con cambios locales sin commit
  ALLOW_UNPUSHED_DEPLOY=1   Permite deploy con commits locales no pusheados
EOF
}

ensure_clean_worktree() {
  if [[ "${ALLOW_DIRTY_DEPLOY:-0}" == "1" ]]; then
    echo "WARNING: deploy con cambios locales sin commit habilitado por ALLOW_DIRTY_DEPLOY=1" >&2
    return
  fi

  local status
  status="$(git -C "$ROOT_DIR" status --porcelain)"
  if [[ -n "$status" ]]; then
    echo "ERROR: hay cambios locales sin commit. Para garantizar que se despliega la version actual del repo remoto, primero commit/push o limpia el working tree." >&2
    echo >&2
    printf '%s\n' "$status" >&2
    echo >&2
    echo "Override consciente: ALLOW_DIRTY_DEPLOY=1 $0 ${1:-all}" >&2
    exit 1
  fi
}

sync_repo() {
  if [[ "${SKIP_REPO_SYNC:-0}" == "1" ]]; then
    echo "WARNING: saltando sincronizacion git por SKIP_REPO_SYNC=1" >&2
    return
  fi

  cd "$ROOT_DIR"

  local upstream
  upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
  if [[ -z "$upstream" ]]; then
    echo "ERROR: la rama actual no tiene upstream configurado; no puedo saber cual es la version mas nueva del repo remoto." >&2
    echo "Configura upstream o usa SKIP_REPO_SYNC=1 si quieres desplegar exactamente esta copia local." >&2
    exit 1
  fi

  git fetch --prune

  local counts behind ahead
  counts="$(git rev-list --left-right --count "$upstream"...HEAD)"
  read -r behind ahead <<< "$counts"

  if [[ "$behind" != "0" ]]; then
    ensure_clean_worktree "$@"
    echo "La rama local esta $behind commit(s) atras de $upstream; actualizando con git pull --ff-only..."
    git pull --ff-only
  fi

  counts="$(git rev-list --left-right --count "$upstream"...HEAD)"
  read -r behind ahead <<< "$counts"

  if [[ "$behind" != "0" ]]; then
    echo "ERROR: la rama local sigue atras de $upstream despues del pull." >&2
    exit 1
  fi

  if [[ "$ahead" != "0" && "${ALLOW_UNPUSHED_DEPLOY:-0}" != "1" ]]; then
    echo "ERROR: hay $ahead commit(s) locales no pusheados. Para que deploy sea la version actual del repo remoto, haz push primero." >&2
    echo "Override consciente: ALLOW_UNPUSHED_DEPLOY=1 $0 ${1:-all}" >&2
    exit 1
  fi
}

prepare_deploy() {
  sync_repo "$@"
  ensure_clean_worktree "$@"

  DEPLOY_COMMIT="$(git -C "$ROOT_DIR" rev-parse --short HEAD)"
  if [[ -n "$(git -C "$ROOT_DIR" status --porcelain)" ]]; then
    DEPLOY_COMMIT="$DEPLOY_COMMIT-dirty"
  fi
  DEPLOY_TIME="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

  echo "Deploying commit $DEPLOY_COMMIT at $DEPLOY_TIME"
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
  cd "$ROOT_DIR"
  gcloud run deploy "$BACKEND_SERVICE" \
    --source=. \
    --region="$REGION" \
    --project="$PROJECT" \
    --update-env-vars="DEPLOY_COMMIT=$DEPLOY_COMMIT,DEPLOY_TIME=$DEPLOY_TIME"
}

deploy_front() {
  cd "$BACKOFFICE_DIR"
  rm -rf .vercel/output .next
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
  if [[ -z "$deployment_url" ]]; then
    deployment_url="$(
      printf '%s\n' "$deploy_output" \
        | sed -n 's/^\(https:\/\/[^ ]*\.vercel\.app\)$/\1/p' \
        | tail -1
    )"
  fi
  if [[ -n "$deployment_url" ]]; then
    npx --yes vercel@latest alias set "$deployment_url" "$BACKOFFICE_EXTRA_ALIAS"
  else
    echo "WARNING: could not detect Vercel deployment URL for alias $BACKOFFICE_EXTRA_ALIAS" >&2
  fi
}

ACTION="${1:-all}"

case "$ACTION" in
  backend)            prepare_deploy "$ACTION"; deploy_backend ;;
  front)              prepare_deploy "$ACTION"; deploy_front ;;
  all)                prepare_deploy "$ACTION"; deploy_backend && deploy_front ;;
  logs-backend)       logs_backend_read ;;
  logs-backend-tail)  logs_backend_tail ;;
  logs-front)         cd "$BACKOFFICE_DIR" && npx --yes vercel@latest logs --follow ;;
  -h|--help)          usage ;;
  *)                  usage; exit 1 ;;
esac
