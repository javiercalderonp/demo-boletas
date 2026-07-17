# Cloud Run Operations

Ultima actualizacion: 2026-07-09

## Arquitectura objetivo

- Backend FastAPI en Cloud Run: webhook WhatsApp, API backoffice, jobs protegidos, OCR, GCS, SQLite/Sheets, DocuSign y OpenAI.
- Backoffice Next.js en Cloud Run: UI operativa, consume el backend con `NEXT_PUBLIC_API_BASE_URL`.
- Cloud Scheduler: invoca jobs internos con `X-Scheduler-Token`.
- Secret Manager: un secreto por credencial sensible.
- GCS privado: boletas originales y PDFs consolidados.
- SQLite persistente: datastore demo recomendado para evitar cuotas de Sheets. Google Sheets queda como compatibilidad.
- Dominios recomendados: `api.<dominio>` y `backoffice.<dominio>`.

## Servicios y responsabilidades

Backend:
- Recibir `GET /webhook` y `POST /webhook`.
- Exponer `/api/*` para backoffice.
- Generar PDFs consolidados y URLs firmadas.
- Iniciar y recibir flujos DocuSign.
- Ejecutar jobs protegidos bajo `/jobs/*`.

Frontend:
- Servir el backoffice Next.js.
- No contener secretos server-side.
- Usar `NEXT_PUBLIC_API_BASE_URL` para apuntar al backend publicado.

Scheduler:
- Ejecutar recordatorios y jobs operativos.
- Enviar `X-Scheduler-Token`.
- No depender de cron local para producción.

## Empaquetado

Backend:
- `Dockerfile` usa `python:3.11-slim`.
- Instala `requirements.txt`.
- Arranca con `uvicorn app.main:app --host 0.0.0.0 --port ${PORT}`.
- Usa `PORT=8080` por defecto.

Backoffice:
- `backoffice/Dockerfile` usa build multi-stage con `npm ci`, `npm run build` y `npm run start`.
- Usa `PORT=8080`.
- Requiere `NEXT_PUBLIC_API_BASE_URL` en build/runtime.

## Variables de entorno

Backend no secretas:
- `APP_ENV=prod`
- `DEBUG=false`
- `LOG_LEVEL=INFO`
- `LOG_FORMAT=json`
- `PUBLIC_BASE_URL=https://api.<dominio>`
- `BACKOFFICE_FRONTEND_ORIGIN=https://backoffice.<dominio>`
- `BACKOFFICE_FRONTEND_ORIGINS=https://backoffice.<dominio>`
- `WHATSAPP_PROVIDER=meta`
- `PERSISTENCE_BACKEND=sqlite`
- `SQLITE_DATABASE_PATH=/tmp/expense_agent.sqlite3` para demo de una instancia, o un volumen/ruta persistente si el ambiente lo provee
- `GOOGLE_SHEETS_SPREADSHEET_ID` solo si se mantiene Sheets
- `GCS_BUCKET_NAME`
- `GCS_RECEIPTS_PREFIX=receipts/`
- `GCS_REPORTS_PREFIX=reports/`
- `DOCUMENT_AI_PROJECT_ID`
- `DOCUMENT_AI_LOCATION`
- `DOCUMENT_AI_PROCESSOR_ID`
- `OPENAI_MODEL`
- `OPENAI_BASE_URL=https://api.openai.com/v1`
- `SCHEDULER_REMINDER_WINDOW_MINUTES`
- `SCHEDULER_NEEDS_INFO_TIMEOUT_HOURS=6`
- `SCHEDULER_NEEDS_INFO_REMINDER_BEFORE_HOURS=2`
- `SCHEDULER_MORNING_HOUR_LOCAL`
- `SCHEDULER_EVENING_HOUR_LOCAL`
- `DOCUSIGN_ENABLED`
- `DOCUSIGN_BASE_URL`
- `DOCUSIGN_ACCOUNT_ID`
- `DOCUSIGN_RETURN_URL=https://api.<dominio>/docusign/callback`

Backend secretos:
- `BACKOFFICE_AUTH_SECRET`
- `BACKOFFICE_DEFAULT_ADMIN_EMAIL`
- `BACKOFFICE_DEFAULT_ADMIN_PASSWORD`
- `META_ACCESS_TOKEN`
- `META_PHONE_NUMBER_ID`
- `META_WABA_ID`
- `META_VERIFY_TOKEN`
- `META_APP_SECRET`
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_WHATSAPP_FROM`
- `OPENAI_API_KEY`
- `SCHEDULER_ENDPOINT_TOKEN`
- `DOCUSIGN_INTEGRATION_KEY`
- `DOCUSIGN_SECRET_KEY`
- `DOCUSIGN_ACCESS_TOKEN`
- `DOCUSIGN_REFRESH_TOKEN`

Frontend:
- `NEXT_PUBLIC_API_BASE_URL=https://api.<dominio>/api`

## Credenciales Google

Preferido en producción:
- No configurar `GOOGLE_APPLICATION_CREDENTIALS`.
- Asociar una service account al servicio Cloud Run.
- Otorgar IAM mínimo a esa service account.

Alternativa temporal:
- Montar JSON desde Secret Manager.
- Configurar `GOOGLE_APPLICATION_CREDENTIALS` apuntando al path montado.
- Rotar y eliminar copias locales del JSON.

## IAM mínimo

Backend runtime:
- `roles/secretmanager.secretAccessor` sobre secretos requeridos.
- `roles/storage.objectAdmin` limitado al bucket privado de documentos.
- Permisos de Document AI processor invoker/reader según proyecto.
- Acceso a Google Sheets mediante share explícito al email de service account o ADC autorizado.

Scheduler:
- Preferido: invocación autenticada a Cloud Run.
- MVP: `X-Scheduler-Token` compartido desde Secret Manager.

Deploy/CI:
- Cloud Build/Run deployer.
- Artifact Registry writer si se usa repositorio de imágenes.

## Secret Manager y rotación

Usar un secreto por credencial:
- `backoffice-auth-secret`
- `backoffice-default-admin-email`
- `backoffice-default-admin-password`
- `meta-access-token`
- `meta-app-secret`
- `openai-api-key`
- `scheduler-endpoint-token`
- `docusign-integration-key`
- `docusign-secret-key`
- `docusign-access-token`
- `docusign-refresh-token`

Rotación:
1. Crear nueva versión del secreto.
2. Actualizar Cloud Run para usar `latest` o la versión nueva.
3. Desplegar/reiniciar servicio.
4. Probar flujo afectado.
5. Deshabilitar versión anterior cuando el flujo esté verificado.

## Bootstrap y preflight

Bootstrap inicial de APIs, service accounts, bucket y secretos placeholder:

```bash
PROJECT_ID=<project-id> \
REGION=us-central1 \
GCS_BUCKET_NAME=<bucket-privado> \
scripts/gcp_demo_bootstrap.sh
```

Antes de desplegar, validar variables productivas:

```bash
python3 scripts/production_preflight.py --env-file .env.production
```

El preflight falla si `DEBUG` no es `false`, si `APP_ENV` no es `prod`, si faltan secretos críticos, si `META_VALIDATE_SIGNATURE` no está activo para Meta, o si DocuSign sigue apuntando a `demo.docusign.net`.

## Deploy

Backend:
```bash
python3 scripts/production_preflight.py --env-file .env.production

gcloud run deploy viaticos-backend \
  --source=. \
  --region=us-central1 \
  --service-account=<backend-runtime-sa>@<project-id>.iam.gserviceaccount.com \
  --min-instances=1 \
  --set-env-vars APP_ENV=prod,DEBUG=false,LOG_FORMAT=json,PERSISTENCE_BACKEND=sqlite,SQLITE_DATABASE_PATH=/tmp/expense_agent.sqlite3
```

Backoffice:
```bash
gcloud run deploy viaticos-backoffice \
  --source=backoffice \
  --region=us-central1 \
  --set-env-vars NEXT_PUBLIC_API_BASE_URL=https://api.<dominio>/api
```

## Cloud Scheduler

Job mínimo:
```bash
gcloud scheduler jobs create http viaticos-reminders \
  --schedule="*/10 * * * *" \
  --time-zone="America/Santiago" \
  --uri="https://api.<dominio>/jobs/reminders/run" \
  --http-method=POST \
  --headers="X-Scheduler-Token=${SCHEDULER_ENDPOINT_TOKEN}"
```

## Verificación E2E previa a salida

- `GET /health` responde `{"status":"ok"}`.
- `/docs`, `/redoc`, `/openapi.json` no existen con `DEBUG=false`.
- Login backoffice y refresh de token funcionan.
- Dashboard/listados/detalles cargan desde el backend productivo.
- Webhook Meta verifica challenge y rechaza firmas inválidas.
- Recepción de texto, imagen y PDF.
- OCR, extracción, preguntas faltantes y guardado.
- Revisión manual aprueba/rechaza y notifica por WhatsApp.
- Scheduler ejecuta recordatorios con token.
- PDF consolidado se genera en GCS.
- DocuSign crea envelope y procesa callback.
- Cálculo final y mensaje final de rendición.

## Recuperación operativa

Logs:
```bash
gcloud run services logs read viaticos-backend --region=us-central1 --limit=100
```

Reintentar scheduler:
```bash
curl -X POST https://api.<dominio>/jobs/reminders/run \
  -H "X-Scheduler-Token: ${SCHEDULER_ENDPOINT_TOKEN}"
```

Problemas típicos:
- Meta token expirado: rotar `META_ACCESS_TOKEN`, reiniciar backend y probar envío.
- SQLite inaccesible: revisar permisos/ruta `SQLITE_DATABASE_PATH`; si se usa `/tmp`, recordar que es efímero por instancia.
- Sheets inaccesible: si se usa compatibilidad Sheets, revisar share de spreadsheet a service account, cuotas y logs.
- Document AI falla: revisar processor id, región y permisos.
- GCS falla: revisar bucket privado, IAM y prefijos.
- DocuSign falla: revisar base URL, token/refresh token y callback público.
