# Arquitectura del sistema - Demo Boletas

Ultima actualizacion: 2026-05-05

## Resumen ejecutivo

`demo-boletas` es un MVP para rendicion de gastos por WhatsApp. El sistema recibe boletas, facturas, boletas de honorarios y comprobantes, extrae datos con OCR, completa informacion faltante conversando con el usuario, registra la rendicion en Google Sheets, permite revision desde un backoffice web y genera un PDF consolidado para aprobacion/firma.

La arquitectura actual esta separada en dos aplicaciones:

- un backend FastAPI desplegado en Google Cloud Run
- un backoffice Next.js desplegado en Vercel

Los datos operacionales viven en Google Sheets. Los archivos binarios, como boletas originales y reportes consolidados, viven en Google Cloud Storage. OCR usa Google Document AI. WhatsApp usa Meta Cloud API en el ambiente actual. La firma electronica usa DocuSign demo.

## Hosting actual

| Componente | Donde esta hosteado actualmente | Evidencia | Notas |
| --- | --- | --- | --- |
| Backend API | Google Cloud Run, servicio `viaticos-backend`, region `us-central1` | [deploy.sh](/Users/javiercalderon/demo-boletas/deploy.sh) y health live | URL actual: `https://viaticos-backend-337678027134.us-central1.run.app`. |
| Backoffice web | Vercel | [deploy.sh](/Users/javiercalderon/demo-boletas/deploy.sh), [backoffice/lib/api.ts](/Users/javiercalderon/demo-boletas/backoffice/lib/api.ts) y verificacion HTTP | Aliases actuales: `https://expenseops-backoffice.vercel.app` y `https://viaticos-backoffice.vercel.app`. |
| API usada por backoffice | Cloud Run | [backoffice/lib/api.ts](/Users/javiercalderon/demo-boletas/backoffice/lib/api.ts) | Default productivo: `https://viaticos-backend-337678027134.us-central1.run.app/api`. |
| Base de datos operacional | Google Sheets | [services/sheets_service.py](/Users/javiercalderon/demo-boletas/services/sheets_service.py), [.env local enmascarado] | Spreadsheet configurado: `1vFTnwfm-3HR_bfg8EUHnV4R-rnIZxM1m0uJGLr855Ts`. |
| Storage de boletas y reportes | Google Cloud Storage | [services/storage_service.py](/Users/javiercalderon/demo-boletas/services/storage_service.py), health live | Bucket actual: `viaticos-receipts-bucket`. |
| OCR | Google Document AI | [services/ocr_service.py](/Users/javiercalderon/demo-boletas/services/ocr_service.py), health live | Proyecto `biaticos-488419`, location `us`, processor `c1b3f4b54d4934cf`. |
| WhatsApp | Meta Cloud API | [services/whatsapp_service.py](/Users/javiercalderon/demo-boletas/services/whatsapp_service.py), health live | `WHATSAPP_PROVIDER=meta`; WABA y phone number configurados por variables de entorno. |
| LLM | OpenAI API | [services/llm_service.py](/Users/javiercalderon/demo-boletas/services/llm_service.py), health live | Modelo actual: `gpt-4o-mini`. |
| Firma electronica | DocuSign demo | [services/docusign_service.py](/Users/javiercalderon/demo-boletas/services/docusign_service.py), health live | Base URL actual: `https://demo.docusign.net/restapi`. |
| Codigo fuente remoto | GitHub | `git remote -v` local | Repo: `https://github.com/javiercalderonp/demo-boletas.git`. |

Verificacion live realizada el 2026-05-05:

- `GET /health` del backend respondio `status=ok`.
- Cloud Run reporto `deploy_commit=041e9b5` y `deploy_time=2026-05-05T20:25:29Z`.
- Los dos aliases de Vercel respondieron `HTTP 200` con header `server: Vercel`.

## Vista logica

```text
Empleado por WhatsApp
  |
  | Meta Cloud API webhook
  v
Cloud Run: viaticos-backend
  |
  +-- FastAPI: app/main.py
  +-- Servicios de dominio: services/*
  |
  +-- Google Document AI
  |     +-- OCR y extraccion de campos
  |
  +-- OpenAI API
  |     +-- clasificacion, asistencia conversacional y preguntas sobre rendicion
  |
  +-- Google Sheets
  |     +-- empresas
  |     +-- Employees
  |     +-- ExpenseCases
  |     +-- Expenses
  |     +-- Conversations
  |     +-- ExpenseCaseDocuments
  |     +-- BackofficeUsers
  |
  +-- Google Cloud Storage
  |     +-- receipts/
  |     +-- reports/
  |
  +-- DocuSign demo
        +-- envelope de firma
        +-- callback de firma

Backoffice Next.js en Vercel
  |
  | HTTPS + Bearer token
  v
Cloud Run /api/*
```

## Backend

### Runtime

El backend es una app FastAPI definida en [app/main.py](/Users/javiercalderon/demo-boletas/app/main.py).

El contenedor se define en [Dockerfile](/Users/javiercalderon/demo-boletas/Dockerfile):

- imagen base: `python:3.11-slim`
- comando: `uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1`
- puerto default: `8080`

El despliegue se hace desde source a Cloud Run con [deploy.sh](/Users/javiercalderon/demo-boletas/deploy.sh):

```bash
gcloud run deploy viaticos-backend \
  --source=. \
  --region=us-central1 \
  --project=biaticos-488419
```

### Servicios internos

En `create_app()` se inicializa un `ServiceContainer` con:

- `SheetsService`: persistencia y lectura/escritura en Google Sheets
- `BackofficeAuthService`: login y tokens del backoffice
- `BackofficeService`: consultas agregadas para la UI
- `ExpenseCaseService`: manejo de rendiciones/casos
- `GCSStorageService`: subida de boletas y reportes a GCS
- `ConsolidatedDocumentService`: generacion de PDF consolidado
- `DocusignService`: creacion de envelopes y URLs de firma
- `OCRService`: extraccion de datos desde documentos
- `ExpenseService`: normalizacion, validacion y guardado de gastos
- `ConversationService`: estado conversacional de WhatsApp
- `WhatsAppService`: recepcion/envio de mensajes
- `SchedulerService`: recordatorios y cierre de rendiciones

### Endpoints principales

Publicos/operacionales:

- `GET /health`
- `GET /webhook`
- `POST /webhook`
- `GET /docusign/callback`
- `GET /r/sign/{document_id}`

Jobs internos:

- `POST /jobs/reminders/run`
- `POST /jobs/documents/consolidated/generate`
- `POST /jobs/documents/signature/start`
- `POST /jobs/docusign/oauth/exchange`

Testing/dev:

- `POST /test/simulate`
- `POST /test/reset`

Backoffice:

- rutas bajo `/api/*`, definidas en [app/api/backoffice.py](/Users/javiercalderon/demo-boletas/app/api/backoffice.py)

## Backoffice

El backoffice es una app Next.js en [backoffice/](/Users/javiercalderon/demo-boletas/backoffice).

Stack:

- Next.js 15
- React 19
- Tailwind CSS
- TypeScript
- componentes React propios

Deploy:

- Vercel produccion via `npx vercel deploy --prebuilt --prod`
- alias adicional `expenseops-backoffice.vercel.app`
- alias tambien observado funcionando: `viaticos-backoffice.vercel.app`

El cliente API esta en [backoffice/lib/api.ts](/Users/javiercalderon/demo-boletas/backoffice/lib/api.ts). En produccion usa por defecto:

```text
https://viaticos-backend-337678027134.us-central1.run.app/api
```

En local usa:

```text
http://localhost:8000/api
```

Autenticacion del backoffice:

- login en `/api/auth/login`
- token tipo Bearer guardado en `localStorage`
- validacion server-side con `BackofficeAuthService`
- usuarios guardados en la hoja `BackofficeUsers`

## Flujo principal de una boleta

1. El empleado envia una imagen o PDF por WhatsApp.
2. Meta Cloud API llama `POST /webhook` en Cloud Run.
3. `WhatsAppService` valida/procesa el evento.
4. `GCSStorageService` descarga el media y lo guarda en GCS bajo `receipts/`.
5. `OCRService` procesa el documento con Google Document AI.
6. `ExpenseService` normaliza campos como comercio, fecha, total, moneda, tipo de documento y pais.
7. `LLMService` puede clasificar categoria, tipo de documento o responder preguntas.
8. `ConversationService` identifica datos faltantes y pregunta por WhatsApp.
9. Cuando el usuario confirma, se crea un registro en `Expenses`.
10. El backoffice revisa, aprueba, observa o rechaza gastos.
11. Al cierre del caso, `ConsolidatedDocumentService` genera el PDF consolidado.
12. El PDF se guarda en GCS bajo `reports/`.
13. `DocusignService` puede iniciar firma en DocuSign demo.
14. El callback de DocuSign actualiza `ExpenseCaseDocuments` y el estado de la rendicion.

## Modelo de datos

La fuente de verdad operacional es Google Sheets. El servicio mantiene compatibilidad con nombres legacy como `Trips` y `TripDocuments`, pero el modelo preferido actual es:

- `empresas`
- `Employees`
- `ExpenseCases`
- `Expenses`
- `Conversations`
- `ExpenseCaseDocuments`
- `BackofficeUsers`

### ExpenseCases

Representa una rendicion/caso.

Campos importantes:

- `case_id`
- `phone`
- `employee_phone`
- `context_label`
- `country`
- `cost_centers`
- `status`
- `rendicion_status`
- `fondos_entregados`
- `fondos_por_centro`
- `settlement_direction`
- `settlement_amount_clp`

### Expenses

Representa un documento/gasto individual.

Campos importantes:

- `expense_id`
- `phone`
- `case_id`
- `merchant`
- `date`
- `currency`
- `total`
- `total_clp`
- `category`
- `country`
- `status`
- `processing_status`
- `review_reason`
- `document_type`
- `receipt_storage_provider`
- `receipt_object_key`
- `source_message_id`
- campos tributarios como `invoice_number`, `tax_amount`, `issuer_tax_id`, `receiver_tax_id`

### Conversations

Guarda el estado conversacional por telefono:

- `phone`
- `case_id`
- `state`
- `current_step`
- `context_json`
- `updated_at`

Estados relevantes:

- `WAIT_RECEIPT`
- `PROCESSING`
- `NEEDS_INFO`
- `CONFIRM_SUMMARY`
- `DONE`
- `WAIT_SUBMISSION_CLOSURE_CONFIRMATION`

### ExpenseCaseDocuments

Guarda reportes consolidados y firma:

- `document_id`
- `phone`
- `case_id`
- `storage_provider`
- `object_key`
- `expense_count`
- `total_clp`
- `signature_provider`
- `signature_status`
- `docusign_envelope_id`
- `signature_url`
- `signature_completed_at`

## Storage

Google Cloud Storage se usa para objetos binarios:

- boletas/facturas/comprobantes originales bajo `receipts/`
- PDFs consolidados bajo `reports/`

Bucket actual:

```text
viaticos-receipts-bucket
```

Los links entregados al backoffice se generan como signed URLs de corta duracion. El TTL actual configurado es `900` segundos para boletas/reportes generales y `1800` segundos para documentos usados por DocuSign.

## OCR y extraccion

`OCRService` usa Google Document AI cuando estan configurados:

- `DOCUMENT_AI_PROJECT_ID`
- `DOCUMENT_AI_LOCATION`
- `DOCUMENT_AI_PROCESSOR_ID`

Configuracion actual verificada:

- proyecto: `biaticos-488419`
- location: `us`
- processor: `c1b3f4b54d4934cf`

Si Document AI no esta habilitado, existe un extractor placeholder para pruebas locales.

## LLM

`LLMService` usa OpenAI API cuando hay `OPENAI_API_KEY`.

Usos actuales:

- clasificacion de categoria
- clasificacion de tipo de documento
- respuesta a preguntas generales sobre el flujo
- respuesta a preguntas sobre la rendicion activa con contexto de caso
- clasificacion de intencion del mensaje

Modelo actual:

```text
gpt-4o-mini
```

## WhatsApp

El proveedor actual es Meta:

```text
WHATSAPP_PROVIDER=meta
```

El sistema tambien conserva soporte para Twilio, pero el health live y `.env` local enmascarado indican que el ambiente actual usa Meta Cloud API.

Endpoints:

- `GET /webhook`: verificacion de webhook Meta
- `POST /webhook`: recepcion de mensajes/eventos

## Firma electronica

DocuSign esta habilitado en ambiente demo:

```text
DOCUSIGN_ENABLED=true
DOCUSIGN_BASE_URL=https://demo.docusign.net/restapi
```

Flujo:

1. Se genera un PDF consolidado en GCS.
2. Se crea un envelope en DocuSign usando una URL remota firmada.
3. Se obtiene una URL de firma embebida.
4. El usuario firma.
5. DocuSign redirige a `/docusign/callback`.
6. El backend marca el documento como `completed` y actualiza la rendicion.

## Seguridad

- El backoffice usa tokens HMAC propios generados por `BackofficeAuthService`.
- Los usuarios del backoffice se guardan en `BackofficeUsers`.
- Las contrasenas se almacenan con PBKDF2-SHA256 y salt.
- Las llamadas del backoffice a la API usan `Authorization: Bearer <token>`.
- CORS permite origins configurados y defaults productivos/locales.
- WhatsApp Meta puede validar firma si `META_VALIDATE_SIGNATURE=true`; actualmente esta en `false` en `.env` local enmascarado.
- Jobs sensibles usan `SCHEDULER_ENDPOINT_TOKEN`.

## Variables y configuracion relevante

No incluir secretos en documentacion. Las variables no sensibles relevantes son:

- `PUBLIC_BASE_URL=https://viaticos-backend-337678027134.us-central1.run.app`
- `BACKOFFICE_FRONTEND_ORIGIN=https://viaticos-backoffice.vercel.app`
- `GOOGLE_SHEETS_SPREADSHEET_ID=1vFTnwfm-3HR_bfg8EUHnV4R-rnIZxM1m0uJGLr855Ts`
- `GCS_BUCKET_NAME=viaticos-receipts-bucket`
- `GCS_RECEIPTS_PREFIX=receipts/`
- `GCS_REPORTS_PREFIX=reports/`
- `DOCUMENT_AI_PROJECT_ID=biaticos-488419`
- `DOCUMENT_AI_LOCATION=us`
- `OPENAI_MODEL=gpt-4o-mini`
- `META_GRAPH_VERSION=v25.0`
- `DOCUSIGN_BASE_URL=https://demo.docusign.net/restapi`

## Deploy

Backend:

```bash
./deploy.sh backend
```

Backoffice:

```bash
./deploy.sh front
```

Ambos:

```bash
./deploy.sh all
```

Logs backend:

```bash
./deploy.sh logs-backend
./deploy.sh logs-backend-tail
```

Logs front:

```bash
./deploy.sh logs-front
```

## Limitaciones actuales

- Google Sheets funciona como base de datos: es practico para MVP, pero no ideal para alta concurrencia, integridad transaccional o reporting complejo.
- El backend corre con `--workers 1`, por lo que escala principalmente con instancias de Cloud Run, no con multiples workers por contenedor.
- Parte del lenguaje legacy de `Trips`/`TripDocuments` sigue presente por compatibilidad.
- El ambiente reporta `APP_ENV=dev` aun estando desplegado en URLs productivas.
- Validacion de firma Meta esta desactivada en la configuracion local observada.
- No se ve un pipeline CI/CD formal; el deploy actual se ejecuta por script.

## Recomendaciones operativas

- Mover la fuente de verdad a Postgres si el volumen o concurrencia crece.
- Activar validacion de firma Meta en produccion.
- Asegurar backups/export periodico de Google Sheets y GCS.
- Documentar owners de los recursos GCP, Vercel, Meta, DocuSign y OpenAI.
- Separar explicitamente ambientes `dev`, `staging` y `prod`.
- Mantener secretos solo en Secret Manager/Vercel env vars, nunca en archivos versionados.
