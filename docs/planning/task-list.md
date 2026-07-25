# Task List — Proyecto Rendiciones

## Infraestructura / Deploy

### Completado — Deploy demo (Cloud Run backend + Vercel backoffice)

- [x] **Ordenar documentos y recursos sueltos del repositorio**
  - Documentación de planificación agrupada en `docs/planning/`
  - Flujo funcional movido a `docs/workflows/`
  - Imágenes fuente agrupadas en `assets/branding/`
  - Residuos vacíos y copia duplicada del logo eliminados
  - Referencias internas y exclusiones de despliegue actualizadas

- [x] **Refactor ADC (ADC-first, file-path opcional)**
  - `services/sheets_service.py`, `services/storage_service.py` y `app/config.py` aceptan credenciales por defecto del entorno cuando `GOOGLE_APPLICATION_CREDENTIALS` está vacío
  - Preservada la ruta legacy con archivo JSON para seeding y desarrollo local
  - 41/41 tests passing

- [x] **Packaging backend (Cloud Run-ready)**
  - `Dockerfile` Python 3.11-slim con `uvicorn app.main:app`, `PORT` por env
  - `.dockerignore` y `.gcloudignore` excluyen `.env`, SA JSON, backoffice, tests, scripts, node_modules

- [x] **GCP setup**
  - APIs habilitadas: Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Cloud Scheduler, IAM Credentials
  - Artifact Registry repo `viaticos` en `us-central1`
  - SA `javier@biaticos-488419.iam.gserviceaccount.com` con roles: `documentai.apiUser`, `secretmanager.secretAccessor`, `storage.objectAdmin`, `iam.serviceAccountTokenCreator` (self, para signed URLs)
  - Bucket GCS existente `viaticos-receipts-bucket` reutilizado
  - Secrets cargados en Secret Manager: `META_ACCESS_TOKEN`, `META_VERIFY_TOKEN`, `OPENAI_API_KEY`, `DOCUSIGN_ACCESS_TOKEN`, `DOCUSIGN_INTEGRATION_KEY`, `DOCUSIGN_SECRET_KEY`, `SCHEDULER_ENDPOINT_TOKEN`, `BACKOFFICE_AUTH_SECRET` (nuevo), `BACKOFFICE_DEFAULT_ADMIN_PASSWORD`

- [x] **Backend en Cloud Run**
  - Servicio: `viaticos-backend` en `us-central1`
  - URL: `https://viaticos-backend-337678027134.us-central1.run.app`
  - Config: `--min-instances=1 --max-instances=5 --concurrency=10 --timeout=300 --memory=1Gi`
  - Build desde source con Cloud Build (`gcloud run deploy --source`)
  - Env vars de negocio + secrets montados via `--set-secrets`
  - `APP_ENV=prod`, `DEBUG=false` verificado en `/health`

- [x] **Backoffice en Vercel**
  - Proyecto `viaticos-backoffice` (scope `javiercalderonps-projects`)
  - URL: `https://viaticos-backoffice.vercel.app`
  - `NEXT_PUBLIC_API_BASE_URL=https://viaticos-backend-337678027134.us-central1.run.app/api` seteado en production

- [x] **Cloud Scheduler reminders**
  - `viaticos-reminders-morning`: `5 9 * * *` America/Santiago → `POST /jobs/reminders/run`
  - `viaticos-reminders-evening`: `5 20 * * *` America/Santiago → `POST /jobs/reminders/run`
  - Autenticados con `X-Scheduler-Token` desde Secret Manager

- [x] **CORS + URLs canónicas**
  - `BACKOFFICE_FRONTEND_ORIGIN=https://viaticos-backoffice.vercel.app`
  - `PUBLIC_BASE_URL=https://viaticos-backend-337678027134.us-central1.run.app`
  - `DOCUSIGN_RETURN_URL=https://viaticos-backend-337678027134.us-central1.run.app/docusign/callback`
  - Preflight OPTIONS desde origin de Vercel devuelve `Access-Control-Allow-Origin` correcto

- [x] **E2E smoke test**
  - `GET /health` → 200, payload público mínimo `{"status":"ok"}`
  - `GET /webhook?hub.verify_token=...&hub.challenge=...` → 200 con echo del challenge
  - `POST /api/auth/login` (admin) → 200 con JWT válido
  - `GET /api/cases` autenticado → 5 rendiciones (lectura real de Google Sheets vía ADC)

- [x] **Reducir información expuesta en `/health`**
  - Endpoint público reducido a `{"status":"ok"}`
  - Removidos del payload público: proveedor WhatsApp, flags internos, presencia de API keys, modelo OpenAI, datos de scheduler, bucket GCS, Document AI, DocuSign, env y metadata de deploy
  - Agregado test de contrato en `tests/test_backoffice_api.py`

### Pendiente — Cierre manual de integración externa (no automatizable por CLI)

- [ ] **Registrar webhook en Meta for Developers**
  - Callback URL: `https://viaticos-backend-337678027134.us-central1.run.app/webhook`
  - Verify token: `viaticos-meta-webhook-2026`
  - Suscribirse a campos: `messages`, `message_reactions`, `messaging_postbacks`
  - `META_VALIDATE_SIGNATURE=true` ya activado en código/config local
  - Cargar `META_APP_SECRET` real en Cloud Run/Secret Manager antes de probar POST de Meta

- [x] **Automatizar autenticación de DocuSign**
  - Renovación automática con `DOCUSIGN_REFRESH_TOKEN` cuando DocuSign responde 401
  - `exchange_authorization_code` persiste tokens en memoria de settings para el runtime
  - Endpoint OAuth protegido con `X-Scheduler-Token` y sin exponer tokens en respuesta
  - Cubierto por `tests/test_docusign_service.py`

### Alta prioridad — Plan de despliegue cloud de la demo

- [x] **Definir arquitectura objetivo de producción para la demo**
  - Base recomendada: `Cloud Run` para backend FastAPI y `Cloud Run` para frontend Next.js
  - `Cloud Scheduler` para disparar jobs operativos (`/jobs/reminders/run` y futuros jobs seguros)
  - `Secret Manager` para credenciales y secretos
  - `GCS` como storage privado de boletas y PDFs consolidados
  - Mantener `Google Sheets` como datastore del MVP en esta primera etapa
  - Mantener integraciones SaaS externas: `Meta/Twilio`, `OpenAI`, `DocuSign`
  - Definir dominios públicos:
  - `api.<dominio>` para webhook/API
  - `backoffice.<dominio>` para interfaz operativa
  - Documentado en `docs/CLOUD_RUN_OPERATIONS.md` y actualizado en `docs/ARCHITECTURE.md`

- [x] **Separar claramente servicios y responsabilidades**
  - Backend:
  - recibir webhook WhatsApp
  - exponer API del backoffice
  - generar PDFs consolidados
  - iniciar flujos de firma
  - exponer endpoints protegidos para jobs
  - Frontend:
  - servir backoffice Next.js
  - consumir API remota vía `NEXT_PUBLIC_API_BASE_URL`
  - Scheduler:
  - ejecutar recordatorios y tareas horarias sin depender de cron en la VM ni procesos manuales
  - Definir explícitamente qué piezas deben ser stateless para escalar sin fricción
  - Documentado en `docs/CLOUD_RUN_OPERATIONS.md`

- [x] **Preparar empaquetado del backend para Cloud Run**
  - Crear `Dockerfile` para FastAPI con `uvicorn`
  - Agregar `.dockerignore`
  - Definir comando estándar de arranque
  - Exponer puerto vía variable `PORT`
  - Confirmar compatibilidad de dependencias runtime:
  - `fastapi`
  - `uvicorn`
  - `gspread`
  - `google-auth`
  - `google-cloud-storage`
  - `google-cloud-documentai`
  - `twilio`
  - `reportlab`
  - Decidir estrategia de logs estructurados para `Cloud Logging`
  - `Dockerfile` existente validado por revisión; logs JSON configurados con `LOG_FORMAT=json`

- [x] **Preparar empaquetado del backoffice para Cloud Run**
  - Crear `Dockerfile` para build y runtime de Next.js
  - Agregar `.dockerignore`
  - Ejecutar `npm ci` y `npm run build` en etapa de build
  - Arrancar con `npm run start`
  - Verificar que `backoffice/lib/api.ts` quede apuntando al API productiva y no a `localhost`
  - Confirmar variables requeridas en runtime/build:
  - `NEXT_PUBLIC_API_BASE_URL`
  - cualquier otra variable pública necesaria
  - Agregado `backoffice/Dockerfile` y `backoffice/.dockerignore`
  - Verificado con `npm run build`

- [x] **Eliminar dependencia de credenciales locales por archivo**
  - Hoy la app usa `GOOGLE_APPLICATION_CREDENTIALS` como path de archivo local
  - Para producción, definir una estrategia canónica:
  - preferida: service account asociada al servicio con permisos IAM
  - alternativa temporal: secreto JSON montado desde `Secret Manager`
  - Ajustar backend para no asumir rutas locales fuera del contenedor
  - Revisar si `SheetsService`, `GCSStorageService` y `OCRService` pueden autenticarse con credenciales por defecto
  - `SheetsService` ya usa ADC si `GOOGLE_APPLICATION_CREDENTIALS` no está definido; estrategia canónica documentada en `docs/CLOUD_RUN_OPERATIONS.md`

- [x] **Definir inventario completo de variables de entorno por servicio**
  - Backend base:
  - `APP_ENV=prod`
  - `DEBUG=false`
  - `PUBLIC_BASE_URL`
  - `BACKOFFICE_FRONTEND_ORIGIN`
  - `BACKOFFICE_AUTH_SECRET`
  - `BACKOFFICE_DEFAULT_ADMIN_EMAIL`
  - `BACKOFFICE_DEFAULT_ADMIN_PASSWORD`
  - WhatsApp:
  - `WHATSAPP_PROVIDER`
  - `META_ACCESS_TOKEN`, `META_PHONE_NUMBER_ID`, `META_WABA_ID`, `META_VERIFY_TOKEN`, `META_APP_SECRET`
  - o `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`
  - Google:
  - `GOOGLE_SHEETS_SPREADSHEET_ID`
  - `GCS_BUCKET_NAME`
  - `GCS_RECEIPTS_PREFIX`
  - `GCS_REPORTS_PREFIX`
  - `DOCUMENT_AI_PROJECT_ID`
  - `DOCUMENT_AI_LOCATION`
  - `DOCUMENT_AI_PROCESSOR_ID`
  - IA:
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`
  - `OPENAI_BASE_URL`
  - Scheduler:
  - `SCHEDULER_ENDPOINT_TOKEN`
  - `SCHEDULER_REMINDER_WINDOW_MINUTES`
  - `SCHEDULER_NEEDS_INFO_TIMEOUT_HOURS`
  - `SCHEDULER_NEEDS_INFO_REMINDER_BEFORE_HOURS`
  - `SCHEDULER_MORNING_HOUR_LOCAL`
  - `SCHEDULER_EVENING_HOUR_LOCAL`
  - DocuSign:
  - `DOCUSIGN_ENABLED`
  - `DOCUSIGN_BASE_URL`
  - `DOCUSIGN_ACCOUNT_ID`
  - `DOCUSIGN_INTEGRATION_KEY`
  - `DOCUSIGN_SECRET_KEY`
  - `DOCUSIGN_ACCESS_TOKEN`
  - `DOCUSIGN_RETURN_URL`
  - Frontend:
  - `NEXT_PUBLIC_API_BASE_URL`
  - Dejar una matriz clara de:
  - variable
  - servicio que la usa
  - secreto vs no secreto
  - valor por ambiente
  - Inventario documentado en `docs/CLOUD_RUN_OPERATIONS.md`

- [ ] **Crear infraestructura mínima administrada en GCP**
  - Proyecto GCP dedicado para la demo
  - Habilitar APIs necesarias:
  - `Cloud Run`
  - `Cloud Build`
  - `Artifact Registry`
  - `Secret Manager`
  - `Cloud Scheduler`
  - `Document AI`
  - `Cloud Storage`
  - Crear bucket privado para documentos
  - Crear service accounts separadas idealmente por servicio:
  - backend runtime
  - frontend runtime si hiciera falta
  - deploy/CI
  - Asignar IAM mínimo necesario
  - Automatización preparada en `scripts/gcp_demo_bootstrap.sh` para APIs, service accounts, bucket privado, IAM mínimo y secretos placeholder

- [x] **Definir permisos mínimos de IAM**
  - Backend debe poder:
  - leer secretos necesarios
  - acceder a `Document AI`
  - leer/escribir en bucket GCS
  - autenticarse contra Google Sheets si se mantiene ese modelo
  - Scheduler debe poder invocar backend de forma autenticada o con token compartido
  - Evitar usar credenciales owner/editor en producción
  - Documentar permiso por componente para facilitar auditoría y rotación
  - Matriz documentada en `docs/CLOUD_RUN_OPERATIONS.md`

- [ ] **Configurar Secret Manager y rotación básica**
  - Crear un secreto por credencial sensible, no un `.env` monolítico si podemos evitarlo
  - Montar/inyectar secretos al backend y al frontend según corresponda
  - Definir nombres consistentes por ambiente
  - Documentar procedimiento de rotación para:
  - `OPENAI_API_KEY`
  - token de Meta/Twilio
  - credenciales DocuSign
  - `BACKOFFICE_AUTH_SECRET`
  - credenciales admin iniciales
  - Bootstrap de secretos placeholder y procedimiento de rotación documentados en `docs/CLOUD_RUN_OPERATIONS.md`

- [ ] **Publicar backend en Cloud Run**
  - Crear servicio backend con HTTPS público
  - Configurar concurrencia, memoria y timeout según carga esperada de OCR/webhook
  - Ajustar `PUBLIC_BASE_URL` al dominio real
  - Configurar `BACKOFFICE_FRONTEND_ORIGIN` con el dominio del front
  - Verificar endpoint `/health` con payload público mínimo `{"status":"ok"}`
  - Verificar endpoints protegidos `/jobs/*`
  - Verificar que el webhook responda correctamente al challenge de Meta si aplica
  - Comando de deploy con service account, envs productivas y `min-instances=1` documentado; validación previa en `scripts/production_preflight.py`

- [ ] **Publicar backoffice en Cloud Run**
  - Crear servicio frontend con HTTPS público
  - Configurar `NEXT_PUBLIC_API_BASE_URL`
  - Validar login, dashboard, listados y detalle de rendiciones/gastos
  - Verificar CORS entre frontend y backend
  - Confirmar que no queden referencias a `localhost`
  - Dockerfile de backoffice existente y comando Cloud Run documentado con `NEXT_PUBLIC_API_BASE_URL`

- [ ] **Configurar dominio, TLS y URLs canónicas**
  - Elegir dominio para demo
  - Asignar subdominios al frontend y backend
  - Configurar certificados administrados
  - Alinear URLs públicas en:
  - webhook Meta/Twilio
  - `PUBLIC_BASE_URL`
  - `DOCUSIGN_RETURN_URL`
  - `NEXT_PUBLIC_API_BASE_URL`
  - Verificar que los redirects de firma usen dominio real y no placeholders

- [ ] **Configurar webhook de WhatsApp en entorno cloud**
  - Si se usa `Meta`:
  - registrar `GET /webhook` y `POST /webhook`
  - validar `META_VERIFY_TOKEN`
  - confirmar `META_VALIDATE_SIGNATURE=true` y `META_APP_SECRET` en Cloud Run
  - revisar vigencia del token y proceso de renovación
  - Si se usa `Twilio`:
  - apuntar webhook inbound al backend publicado
  - activar `TWILIO_VALIDATE_SIGNATURE`
  - probar recepción de texto, imagen y PDFs
  - Documentar proveedor elegido como estándar de la demo

- [ ] **Configurar jobs automáticos con Cloud Scheduler**
  - Crear job para `POST /jobs/reminders/run`
  - Enviar `X-Scheduler-Token`
  - Definir zona horaria correcta para operación
  - Ajustar frecuencia al diseño del reminder window
  - Evaluar jobs separados a futuro para:
  - generación de consolidado
  - inicio de firma
  - housekeeping / reconciliaciones
  - Eliminar dependencia del script local `install_scheduler_cron.sh` para producción
  - Comando Cloud Scheduler con `X-Scheduler-Token` y service account documentado en `docs/CLOUD_RUN_OPERATIONS.md`; bootstrap prepara service account scheduler

- [ ] **Asegurar persistencia y operación de documentos**
  - Validar carga de imágenes/PDF desde proveedor WhatsApp hacia GCS
  - Verificar generación de signed URLs
  - Verificar generación del PDF consolidado en GCS
  - Verificar lectura posterior desde backoffice y flujo DocuSign
  - Confirmar políticas de retención y naming de objetos

- [ ] **Validar integración DocuSign en ambiente público**
  - Ajustar `DOCUSIGN_RETURN_URL` a la URL real del backend
  - Probar:
  - creación de envelope
  - recipient view
  - callback de firma
  - actualización del documento y del caso
  - Definir cómo se manejará expiración/rotación de `DOCUSIGN_ACCESS_TOKEN`
  - Evaluar si conviene formalizar OAuth refresh para no depender de token manual

- [ ] **Fortalecer seguridad mínima para demo operable**
  - `DEBUG=false` en producción
  - secreto fuerte para `BACKOFFICE_AUTH_SECRET`
  - credenciales admin iniciales no hardcodeadas
  - validación de firmas de webhook activada
  - bucket privado, no público
  - [x] endpoints internos `/jobs/*`, OAuth DocuSign y `/test/*` protegidos siempre con `X-Scheduler-Token`
  - [x] `/health` público reducido a payload mínimo sin datos operacionales sensibles
  - revisar exposición accidental de datos sensibles en logs
  - revisar políticas CORS para permitir solo el dominio del backoffice

- [ ] **Agregar observabilidad operativa básica**
  - Logs centralizados en `Cloud Logging`
  - Filtros o métricas para:
  - errores de webhook
  - fallas OCR / Document AI
  - errores de envío WhatsApp
  - fallas Google Sheets
  - fallas GCS
  - fallas DocuSign
  - Crear alertas simples para caídas del backend y errores repetidos
  - Definir panel mínimo de salud para la demo

- [ ] **Ejecutar plan de pruebas end-to-end previo a salida**
  - Healthcheck backend
  - Login backoffice
  - Recepción de mensaje de WhatsApp
  - Recepción de imagen
  - OCR + extracción + preguntas faltantes
  - Confirmación y guardado en Sheets
  - Visualización en backoffice
  - Revisión manual y notificación al usuario
  - Reminder scheduler
  - Generación de consolidado
  - Firma DocuSign o cierre simple
  - Cálculo final de rendición y mensaje final
  - Probar además escenarios de error:
  - token expirado de Meta
  - fallo de Sheets
  - fallo de Document AI
  - documento no identificado
  - Plan documentado en `docs/CLOUD_RUN_OPERATIONS.md`; pendiente ejecución contra ambiente público real

- [x] **Documentar runbook de operación de la demo**
  - Cómo desplegar una nueva versión
  - Cómo rotar secretos
  - Cómo revisar logs
  - Cómo reintentar jobs
  - Cómo validar webhooks
  - Cómo resetear datos demo cuando sea necesario
  - Cómo recuperar si falla Meta/Twilio, Sheets o DocuSign
  - Runbook documentado en `docs/CLOUD_RUN_OPERATIONS.md`

- [x] **Definir siguiente etapa post-demo para endurecimiento**
  - Migración de `Google Sheets` a base de datos real
  - Separación de worker asíncrono si OCR/PDF crecen en costo o latencia
  - CI/CD con build y deploy automáticos
  - Siguiente etapa documentada como pendientes operativos/técnicos en `docs/planning/production-roadmap.md` y `docs/CLOUD_RUN_OPERATIONS.md`
  - Ambientes separados `dev` / `staging` / `prod`
  - Observabilidad más completa y auditoría
  - Gestión más robusta de usuarios/roles del backoffice

## Backend

### Completado

- [x] **Cierre contable mensual — backend MVP**
  - Preview mensual autoritativa con filtros, agregaciones monetarias con `Decimal` y validación de scope por empresa
  - Informe PDF ReportLab, XLSX contable, CSV UTF-8 BOM y ZIP con comprobantes, consolidados y `manifest.json`
  - Persistencia versionada en `MonthlyAccountingExports`, snapshot de IDs/totales, almacenamiento GCS privado y signed URLs de 5 minutos
  - Historial, auditoría de generación/descarga, advertencias por datos incompletos y tolerancia a archivos inaccesibles
  - Cobertura de permisos, mes vacío, monedas, nombres seguros, colisiones, manifest, ZIP, Excel numérico y signed URLs

- [x] **Chatbot con clasificación inteligente de intención**
  - Mensajes de texto en estado `WAIT_RECEIPT` ahora se clasifican por intención usando LLM
  - `case_question`: preguntas sobre presupuesto, centros de costo, gastos registrados → se responden con contexto completo del caso activo (centros de costo, presupuesto, gastos por CC)
  - `general_question`: preguntas sobre cómo usar la app → LLM con contexto genérico
  - `irrelevant`: mensajes fuera de scope → respuesta educada de declive
  - Heurísticas (`_looks_like_rendicion_request`, `_looks_like_question`) pasan `case_context_hint` para usar LLM con contexto cuando los keywords no coinciden
  - Nuevo método `build_case_context_text(phone)` en `ExpenseService` construye contexto rico (presupuesto, centros de costo, gastos por CC, saldo)
  - Nuevos métodos `answer_question_with_case_context` y `classify_message_intent` en `LLMService`

- [x] **Modelo "fondos por rendir"**
  - Columnas: `fondos_entregados`, `rendicion_status`, `user_confirmed_at`, `user_confirmation_status`
  - Balance computado: `monto_rendido_aprobado`, `monto_pendiente_revision`, `saldo_restante`
  - Ciclo de vida: open → pending_user_confirmation → pending_company_review → approved → closed

- [x] **Integración DocuSign con rendiciones**
  - `request_user_confirmation` dispara el flujo existente de PDF consolidado + DocuSign
  - Callback de DocuSign actualiza `user_confirmed_at` y `rendicion_status`
  - Flujo original (`_deliver_submission_closure_package`) preservado

- [x] **Dashboard adaptado al modelo de rendiciones**
  - Stats: rendiciones abiertas, fondos entregados, pendiente revisión, saldo total, docs por revisar
  - Alerts priorizados: saldo negativo (error), rendiciones pendientes (warning), docs sin aprobar (warning)
  - Distribución de estados de rendiciones para gráfico donut

- [x] **Notificaciones automáticas por estado de documento**
  - WhatsApp al usuario cuando un documento es aprobado/rechazado
  - Alerta al operador cuando el saldo se vuelve negativo (vía `_balance_warning` en respuesta)

- [x] **Sistema de review scoring**
  - `ReviewScoreService` con 6 dimensiones ponderadas (0-100)
  - Filtrado y ordenamiento por `review_status` y `review_priority`
  - Estados: needs_manual_review, pending_review, ready_to_approve, observed, approved, rejected

- [x] **Progreso de rendición en flujo WhatsApp**
  - `get_policy_progress()` usa `fondos_entregados` cuando existe (fallback a `max_total_amount`)
  - Mensaje con terminología "Fondos entregados" / "Rendido" / "Saldo restante"

- [x] **Validación de montos en el flujo WhatsApp**
  - Resumen de rendición mostrado siempre después de guardar gasto (incluso con recibos pendientes)
  - Usa `build_policy_progress_message` consistentemente en el flujo de confirmación

- [x] **Reminder automático por tiempo**
  - Alerta tipo `stale_rendicion` (severity: error) en dashboard si rendición lleva ≥3 días en `pending_company_review`
  - Usa `updated_at` del caso para calcular días transcurridos (`STALE_RENDICION_DAYS = 3`)

- [x] **Reportes y exportación CSV**
  - Endpoint `GET /api/cases/export/csv` con datos de rendiciones (caso, empleado, fondos, balance, estado)
  - Endpoint `GET /api/expenses/export/csv` con datos de gastos (expense, empleado, merchant, montos, review)
  - Ambos protegidos con autenticación Bearer token

- [x] **Script de seeding de datos demo (`scripts/seed_demo_data.py`)**
  - Siembra 3 empresas, 10 empleados, 1 admin backoffice, 5 casos en estados distintos (`open`, `pending_company_review`, `pending_user_confirmation`, `approved`, `closed`)
  - Incluye 19 gastos con mezcla de `status` (pending_approval, pending_review, approved, rejected, observed, needs_manual_review), review scores y flags
  - 5 conversaciones (una por caso) en estados `WAIT_RECEIPT`, `DONE`, `WAIT_SUBMISSION_CLOSURE_CONFIRMATION`
  - 3 `ExpenseCaseDocuments` con signature_status (`sent`, `completed`) para casos que pasaron por cierre documental
  - Soporta `--clear-data` y dry-run por defecto (requiere `--confirm` para escribir)

- [x] **Fix detección de divisa en boletas chilenas (bug PEN vs CLP)**
  - OCR `_infer_currency_from_text`: se priorizó check chileno antes de PEN/USD y se reemplazó substring matching por word boundaries (`\bPEN\b`, `\bSOLES\b`, `\bUSD\b`, `\bEUR\b`, `\bCLP\b`, `\bCNY\b`) para evitar falsos positivos con palabras como `PENDIENTE`, `SOLICITUD`, `SOLARIUM`
  - OCR `_pick_currency_value`: mismo ajuste con word boundaries y soporte de `S/` como marcador PEN
  - `expense_service._apply_chile_guardrails` y `_reconcile_country_currency`: ahora overridean cualquier divisa no-CLP (no sólo USD) a CLP cuando hay evidencia fuerte de Chile y no hay marcador explícito de la otra divisa
  - Nuevos helpers `_has_explicit_pen_marker`, `_has_explicit_eur_marker`, `_has_explicit_cny_marker` y wrapper `_has_explicit_currency_marker(text, currency)`

- [x] **Agregar scoping de usuarios backoffice por empresa**
  - Extender `BackofficeUsers` para soportar alcance de datos, con mínimo: `role`, `company_id` y opcionalmente `scope_type` (`global`, `company`)
  - Definir regla base:
  - usuario `admin` o `global` puede ver y operar sobre todas las empresas
  - usuario scoped a empresa solo puede crear rendiciones para su `company_id`
  - usuario scoped a empresa solo puede ver empleados, rendiciones, gastos, conversaciones y exports de su propia empresa
  - Implementar autorización server-side, no solo filtros de frontend
  - Centralizar una función tipo `can_access_company(user, company_id)` y reutilizarla en login/auth, endpoints y servicios backoffice
  - En creación o edición, validar que no se pueda asignar una rendición/empleado/gasto a otra empresa fuera de la jurisdicción del usuario
  - En listados y dashboards, aplicar filtro por `company_id` antes de calcular métricas, alerts y CSVs
  - Definir comportamiento para registros sin `company_id`: bloquear, ocultar o dejar solo para admin
  - Agregar tests de autorización para `GET /api/cases`, `GET /api/expenses`, `GET /api/employees`, `GET /api/dashboard`, exports y `POST /api/cases`
  - Implementado con `services/backoffice_permissions.py`, filtros server-side en `BackofficeService`, validaciones en API y tests de autorización

- [x] **Eliminar gastos asociados al eliminar una rendición**
  - Cuando se elimine un caso/rendición, eliminar también todos los gastos/documentos asociados al `case_id`
  - Asegurar que no queden gastos huérfanos visibles en listados, dashboard, exports ni conversaciones del backoffice
  - Agregar confirmación clara en UI indicando cuántos gastos/documentos serán eliminados junto con la rendición
  - Cubrir con tests de servicio/API para validar el borrado en cascada
  - Implementado con `delete_case_with_related_data`, `delete_expenses_for_case`, UI con conteo y tests de API/servicio

### Alta prioridad — Mejoras flujo WhatsApp

- [x] **Notificaciones por WhatsApp ligadas al documento revisado**
  - Cuando un gasto cambie de estado en backoffice (`approved`, `rejected`, `observed`, `needs_manual_review`), notificar al usuario por WhatsApp
  - Enviar la notificación como respuesta/referencia al mensaje o imagen original cuando el proveedor lo permita
  - Incluir contexto útil: comercio, monto, estado nuevo y siguiente acción esperada
  - Definir fallback cuando no exista `message_id` o el proveedor no soporte reply contextual
  - Implementado para `approve`, `reject`, `observe` y `manual_review`, con reply a `source_message_id` o fallback a último media del chat
  - Cubierto por tests de API

- [x] **Formalizar el flujo completo de cierre de rendición**
  - Separar explícitamente las etapas del caso; hoy el sistema mezcla cierre de carga, cierre documental y cierre financiero
  - Definir y documentar las etapas de negocio:
  - `cierre de carga`: el trabajador terminó de subir boletas y ya no deberían entrar más documentos salvo reapertura
  - `cierre de revisión`: backoffice terminó de revisar todos los documentos cargados
  - `confirmación documental`: generación de PDF consolidado + firma/aceptación del trabajador
  - `liquidación financiera`: cálculo final de quién le debe a quién
  - `cierre total`: el caso quedó completamente liquidado y cerrado
  - Documentar el criterio de avance entre etapas y qué actor destraba cada una
  - Implementado con `rendicion_status`, `closure_method`, `user_confirmation_status`, `settlement_*`, gates de transición y documentación en `docs/workflows/expense-submission.md`

- [x] **Definir regla canónica de "documentos resueltos"**
  - La rendición no debe exigir que todas las boletas estén aprobadas; debe exigir que todas estén resueltas
  - Un documento `approved` cuenta como resuelto y entra al cálculo final
  - Un documento `rejected` o equivalente definitivo cuenta como resuelto y no entra al cálculo final
  - Un documento `observed`, `needs_manual_review`, `pending_review`, `pending_approval` o cualquier estado que requiera acción adicional no cuenta como resuelto
  - Documentar esta regla tanto para backend como para frontend para evitar interpretaciones distintas
  - Centralizado en `services/statuses.py` y validado por `ensure_case_ready_for_document_confirmation`

- [x] **Bloquear avance del caso mientras existan documentos no resueltos**
  - No permitir avanzar a confirmación documental, firma o cierre final si quedan documentos en estados transitorios
  - El backend debe validar esta regla, no solo la UI
  - Mostrar al operador qué documentos bloquean el avance y por qué
  - Definir si existe reapertura del caso de carga cuando el trabajador debe reenviar antecedentes o una nueva boleta
  - Backend bloquea confirmación/cierre con detalle de documentos bloqueantes; cubierto por tests

- [x] **Agregar fase transitoria de "pendiente de antecedentes del trabajador"**
  - Hoy existen estados como `observed` y `needs_manual_review`, pero no un subflujo formal cuando falta información del trabajador
  - Definir cuándo un documento requiere nueva acción del trabajador versus revisión interna del operador
  - Si el trabajador debe responder o reenviar respaldo, el caso debe quedar explícitamente en una fase intermedia
  - Esta fase debe bloquear el cierre de revisión hasta que los documentos vuelvan a quedar resueltos
  - `observed` mapea a `awaiting_employee_input`, notifica al trabajador y bloquea avance hasta resolución

- [x] **Separar cierre documental de liquidación financiera**
  - El estado `closed` hoy se parece más a un cierre documental que a un cierre financiero completo
  - Definir estados distintos para:
  - carga cerrada
  - revisión cerrada
  - confirmación/firma pendiente
  - liquidación pendiente
  - liquidado / cerrado total
  - Evitar que una firma DocuSign implique automáticamente que el caso ya quedó financieramente resuelto
  - Separado con `user_confirmation_status`/firma y `settlement_status`; `close_rendicion` exige liquidación resuelta

- [x] **Soportar dos variantes de cierre documental**
  - Habilitar dos flujos formales de cierre antes de la liquidación financiera:
  - `cierre con DocuSign`: genera PDF consolidado y solicita firma/confirmación formal
  - `cierre simple por WhatsApp`: no usa DocuSign y pide confirmación explícita del trabajador directamente en el chat
  - Definir cuándo se usa cada modalidad:
  - por configuración global
  - por empresa
  - por caso
  - por disponibilidad de email o de integración DocuSign
  - En ambos caminos debe quedar trazabilidad de la aceptación del trabajador y la fecha de confirmación
  - La modalidad elegida no debe cambiar la lógica posterior de liquidación; solo cambia la forma de confirmar el cierre documental
  - Implementado con `closure_method=simple|docusign`, PDF consolidado y confirmación WhatsApp/DocuSign; cubierto por tests de scheduler

- [x] **Implementar cálculo formal de liquidación final**
  - Al terminar la revisión, calcular resultado final usando `fondos_entregados` vs `monto_rendido_aprobado`
  - El cálculo debe considerar solo documentos aprobados; documentos rechazados no deben sumar
  - Clasificar el resultado en tres escenarios:
  - `cuadrado exacto`: no hay deuda entre partes
  - `empresa debe reembolsar`: el trabajador gastó más de lo entregado y corresponde pago adicional
  - `trabajador debe devolver`: gastó menos de lo entregado y corresponde devolución
  - Persistir el resultado y el monto neto final en el caso
  - Implementado en `sync_case_settlement` / `_compute_case_settlement`; cubierto por tests

- [x] **Definir estados explícitos de liquidación financiera**
  - Agregar una capa de estado para la liquidación, separada del estado documental del caso
  - Estados sugeridos:
  - `balanced`
  - `company_owes_employee`
  - `employee_owes_company`
  - `settlement_pending`
  - `settled`
  - Documentar qué transición mueve cada estado y quién la ejecuta
  - Implementado con `SettlementDirection` y `SettlementStatus`; persistido en columnas `settlement_*`

- [x] **Formalizar confirmación de liquidación financiera por WhatsApp**
  - Extender el flujo posterior a la confirmación documental para cubrir los dos escenarios no balanceados
  - Caso `employee_owes_company`:
  - enviar mensaje de saldo + datos bancarios de la empresa
  - pedir comprobante por WhatsApp como imagen o PDF
  - guardar ese comprobante como artefacto del caso, separado de las boletas rendidas (`document_type=settlement_payment_proof`)
  - disparar OCR y dejar el comprobante en revisión financiera manual cuando no haya confianza automática suficiente
  - dejar estado explícito: `pending_employee_payment_proof`, `payment_proof_under_review`, `settled` o `payment_proof_rejected`
  - fallback manual vía backoffice usando `resolve_settlement`
  - Caso `company_owes_employee`:
  - definir cómo se registra el pago al colaborador
  - resolución manual desde backoffice con fecha/momento de resolución y notificación al trabajador
  - dejar estado explícito: `pending_company_payment`, `company_payment_sent`, `settled`
  - asegurar que `close_rendicion` solo quede habilitado cuando la liquidación esté realmente resuelta

- [x] **Resumen final del caso y acciones pendientes por WhatsApp**
  - Una vez cerrada la revisión y calculada la liquidación, enviar un resumen claro por WhatsApp al trabajador
  - Incluir:
  - fondos entregados
  - monto aprobado
  - saldo neto final
  - quién le debe a quién
  - acción pendiente esperada
  - En escenario `balanced`, informar que la rendición quedó cuadrada
  - En escenario `company_owes_employee`, informar que hay un reembolso pendiente a favor del trabajador
  - En escenario `employee_owes_company`, informar que hay una devolución pendiente a favor de la empresa
  - Implementado en mensajes de liquidación de `BackofficeService` y flujo simple/DocuSign

- [x] **Definir cierre total del caso**
  - El caso no debe considerarse completamente cerrado solo porque terminó la revisión o se firmó el PDF
  - Debe existir un último estado de cierre total cuando ya ocurrió la liquidación o se confirmó que no había saldo pendiente
  - Documentar si esta confirmación será manual desde backoffice o si más adelante podrá integrarse con pagos/conciliación
  - `close_rendicion` solo cierra total cuando la liquidación está `settled` o el caso queda balanceado; cubierto por tests

- [x] **Mensaje de bienvenida / onboarding**
  - Detectar primera interacción (sin conversación previa) y enviar saludo personalizado
  - Incluir nombre del empleado, rendición activa y fondos disponibles
  - Contextualiza al usuario antes de que envíe su primer documento
  - Implementado con intro al crear rendición y saludo inicial personalizado; cubierto por tests de `_build_initial_wait_receipt_reply`

- [x] **Comando "estado" / "resumen" / "saldo"**
  - Permitir que el usuario pida su estado actual sin necesidad de enviar un documento
  - Reconocer palabras clave ("estado", "resumen", "saldo", "mis gastos") en `WAIT_RECEIPT`
  - Responder con `build_policy_progress_message` del caso activo
  - Implementado en `ConversationService._heuristic_answer` y `ExpenseService.answer_rendicion_question`; cubierto por tests de resumen/saldo

- [x] **Manejo de texto más inteligente en WAIT_RECEIPT**
  - Reconocer saludos ("hola", "buenos días") y responder amablemente sin pedir foto
  - Reconocer agradecimientos ("gracias", "listo") y no insistir con "envíame una foto"
  - Usar LLM para entender intención del usuario antes de caer en el mensaje genérico
  - Implementado con heurísticas de saludo/preguntas y fallback LLM contextual en `ConversationService`

### Media prioridad

- [x] **Reglas de cierre de rendición**
  - Definir si `close_rendicion` debe exigir que todos los documentos estén resueltos
  - Bloquear cierre si existen documentos en `pending_approval`, `pending_review`, `needs_manual_review` u `observed`
  - Mostrar al operador qué documentos faltan por resolver antes de permitir el cierre
  - Implementado en `ensure_case_ready_for_document_confirmation` y `ensure_case_ready_for_close`

- [x] **Flujo formal de liquidación final**
  - Al terminar la revisión, calcular resultado final usando `fondos_entregados` vs `monto_rendido_aprobado`
  - Clasificar el caso en: cuadrado exacto, empresa debe reembolsar, empleado debe devolver
  - Persistir el resultado de liquidación y el monto neto a favor/en contra
  - Separar claramente cierre documental de cierre financiero
  - Implementado con `settlement_direction`, `settlement_status`, `settlement_amount_clp` y `settlement_net_clp`

- [x] **Resumen final y acciones pendientes por WhatsApp**
  - Enviar al usuario un resumen del caso al finalizar la revisión
  - Incluir: fondos entregados, rendido aprobado, saldo neto y responsable de la siguiente acción
  - Si el empleado debe devolver dinero, indicar que existe devolución pendiente
  - Si la empresa debe pagar diferencia, indicar que existe reembolso pendiente
  - Implementado en `build_case_settlement_whatsapp_message` y mensajes posteriores

- [x] **Estados de liquidación financiera**
  - Definir estados explícitos para el cierre financiero, por ejemplo:
  - `balanced`
  - `employee_owes_company`
  - `company_owes_employee`
  - `settlement_pending`
  - `settled`
  - Implementado en `services/statuses.py` y persistencia `settlement_*`
- [x] **Confirmación rápida ampliada**
  - Aceptar más variantes de confirmación: "dale", "listo", "va", "perfecto", thumbs up emoji
  - Reducir fricción en el paso de confirmación de gasto
  - Implementado para confirmación de gasto y cierre documental simple; cubierto por tests

- [x] **Timeout de conversación en NEEDS_INFO**
  - Si el usuario no responde en X horas mientras se le pide un campo, volver a `WAIT_RECEIPT`
  - Guardar el borrador como pendiente de revisión en backoffice
  - Enviar recordatorio antes del timeout: "Tienes un gasto pendiente de completar..."

- [x] **Soporte para documentos PDF**
  - Muchas facturas llegan como PDF adjunto en WhatsApp
  - Verificar que el OCR soporte PDF o agregar conversión PDF→imagen antes del OCR

- [x] **Auto-confirmación cuando OCR es perfecto**
  - Si todos los campos están completos y review_score ≥ 90 sin flags, auto-guardar
  - Notificar al usuario: "Guardé tu gasto: [merchant] $[total]. Si algo está mal, escribe 'corregir'."
  - Reduce la interacción de 2 mensajes a 1 para el caso ideal

- [x] **Manejo de múltiples rendiciones por persona**
  - Cuando una persona tiene más de un caso activo, el bot debe preguntar a cuál rendición asociar el documento
  - El flujo WhatsApp guarda el OCR temporalmente, pide selección por número/ID y conserva `case_id` al confirmar el gasto
  - `save_confirmed_expense` respeta el `case_id` seleccionado desde el draft

- [x] **Bloquear creación de un caso si la persona ya tiene uno activo**
  - Regla de negocio: una persona no debería tener más de un caso activo al mismo tiempo
  - Validar en backoffice/API antes de crear el caso y devolver error claro al operador
  - Si ya existen múltiples casos activos por datos históricos o inconsistencia, no crear uno nuevo y derivar a resolución manual
  - Definir criterio de resolución: cerrar el caso anterior, fusionar, o marcar conflicto para revisión
  - Implementado en `BackofficeService.create_case`; cubierto por test API de conflicto

- [x] **Sistema de simulación de conversaciones WhatsApp**
  - Generador de boletas/facturas chilenas sintéticas (`scripts/generate_receipt_images.py`)
  - Imágenes Pillow con datos aleatorios: merchant, RUT, items, totales CLP, folio, SII.CL
  - Endpoint `/test/simulate` para procesamiento sincrónico (solo en DEBUG)
  - Endpoint `/test/reset` para resetear conversación de prueba
  - Simulador de conversación (`scripts/simulate_conversation.py`) con media server local
  - Escenarios: happy path, corrección, cancelación, mixed
  - Auto-respuesta inteligente a preguntas del bot

- [x] **Tests**
  - Tests unitarios para `_compute_rendicion_balance`
  - Tests para `ReviewScoreService.compute_review`
  - Tests para las acciones de rendición en backoffice API
  - Tests del flujo WhatsApp de confirmación/firma

### Baja prioridad

- [x] **Resumen diario automático**
  - Mensaje al usuario al final del día con resumen de gastos registrados y saldo
  - Implementado en el slot de cierre diario de `scheduler_service`

- [x] **Contexto de gastos individuales en el chat WhatsApp**
  - `build_case_context_text` ahora incluye el listado detallado de cada gasto (merchant, fecha, monto, estado)
  - El LLM puede responder preguntas como "cuál fue mi último gasto" o "cuál es el estado de mis gastos"
  - Estado mapeado a etiquetas legibles: aprobado, rechazado, pendiente aprobación, pendiente revisión, revisión manual, observado

- [x] **Comando "mis gastos" / "últimos"**
  - Mostrar los últimos 5 gastos registrados con estado (aprobado/pendiente/rechazado)
  - Accesible escribiendo "mis gastos" o "últimos" en el chat
  - Implementado en `ExpenseService.answer_rendicion_question`; cubierto por test de último gasto

- [x] **Soporte multilingüe**
  - Detectar idioma del usuario y responder acorde
  - Persistir `language` en el contexto de conversación
  - Respuestas conversacionales y prompts básicos localizados en español, inglés y portugués

- [x] **Migrar de Google Sheets a base de datos**
  - PostgreSQL o SQLite para producción real
  - Implementado backend SQLite persistente opcional con `PERSISTENCE_BACKEND=sqlite`
  - `SheetsService` conserva la API existente y guarda filas JSON por colección en `SQLITE_DATABASE_PATH`
  - Elimina dependencia operativa de cuotas/rate limits de Google Sheets para demo/local; Postgres queda como evolución para alta concurrencia multi-instancia

---

## Frontend

### Completado

- [x] **Cierre contable mensual — dashboard MVP**
  - Panel entre métricas y operación con selector de empresa, mes y año
  - Vista previa de rendiciones, gastos, total y estados
  - Modal de confirmación con advertencias, generación y estado visible
  - Historial básico con descarga individual de PDF, Excel y ZIP

- [x] **Dashboard rediseñado**
  - 4 cards primarios: fondos entregados, total rendido, pendiente revisión, saldo total
  - 4 cards secundarios: rendiciones abiertas, en revisión, docs por revisar, conversaciones
  - Alerts con severidad (error/warning) y links directos
  - Tabla de rendiciones activas con fondos/aprobado/saldo/estado

- [x] **Gráfico de estado de rendiciones**
  - Donut chart SVG puro (sin dependencias externas) en el dashboard
  - Distribución por estado: abiertas, esperando firma, revisión empresa, aprobadas, cerradas
  - Leyenda con colores y conteos

- [x] **Lista de gastos con review scoring**
  - Filtros rápidos por estado de review con contadores
  - Filtros avanzados con dropdown de review_status
  - Tabla con score, flags, review status, acciones por fila
  - Ordenamiento por review_priority (score + status)
  - Botón "Exportar CSV" para descargar gastos

- [x] **Detalle de gasto con review breakdown**
  - ReviewScoreRing (color-coded por score)
  - 6 barras de breakdown: document_quality, extraction_quality, field_completeness, document_type_confidence, policy_risk, duplicate_risk
  - Review flags como pills de advertencia
  - Acciones: aprobar/rechazar/observar/solicitar revisión

- [x] **Acciones masivas en la lista de gastos**
  - Checkboxes para seleccionar múltiples documentos
  - Select all / deselect all
  - Aprobar/rechazar en batch con diálogo de confirmación
  - Ejecución paralela con estado de loading

- [x] **Lista de rendiciones (ex "Casos")**
  - Título y terminología actualizada a "Rendiciones"
  - Crear rendición con `fondos_entregados`
  - Al crear una rendición, el método de cierre queda por defecto en `Cierre Simple`
  - Tabla con fondos, aprobado, saldo (rojo si negativo), estado, docs
  - Botón "Exportar CSV" para descargar rendiciones

- [x] **Fondos entregados por centro de costo**
  - Al crear una rendición, selector de modo: "Total" o "Por centro de costo"
  - En modo "Por centro de costo", se muestra una fila de input por cada centro de costo definido, con total calculado automáticamente
  - El default es "Total" (campo único, comportamiento anterior)
  - Nuevo campo `fondos_por_centro` (dict) almacenado en backend y Google Sheets
  - El `fondos_entregados` total se calcula como suma de los montos por centro

- [x] **Filtros y búsqueda en rendiciones**
  - Barra de búsqueda por empleado, ID de rendición, o empresa
  - Filtro por estado de rendición (dropdown con todos los estados)
  - Filtro por saldo (positivo/negativo)
  - Botón "Limpiar filtros"

- [x] **Detalle de rendición**
  - Card de balance: fondos entregados, rendido aprobado, pendiente, saldo restante
  - Acciones según estado: solicitar confirmación, esperando firma, aprobar, cerrar
  - Badge de confirmación DocuSign
  - Form editable con fondos_entregados
  - Tabla de documentos con review_score y review_status

- [x] **Historial de actividad en la rendición**
  - Timeline visual con iconos y colores por tipo de evento
  - Eventos: creación, documentos subidos, aprobaciones/rechazos, envío a firma, firma, cierre
  - Ordenado cronológicamente

- [x] **Vista de conversación integrada en la rendición**
  - Componente `ChatPanel` reutilizable extraído de `/conversations/[phone]`
  - Chat con polling, envío de mensajes, y auto-scroll integrado en el detalle de rendición
  - Reemplaza tabla simple de conversaciones

- [x] **Experiencia mobile para Personas, Casos y Gastos**
  - Breakpoint `md` (768px): mobile muestra cards/lista, desktop/tablet mantiene tabla sin cambios
  - Personas: card con nombre + badge estado, grilla 2 cols (teléfono, RUT, empresa, gastos), botón "Ver gastos" y menú `···` (Editar, Activar/Desactivar, Eliminar)
  - Casos: card con badge estado, título rendición + ID, empleado, grilla financiera (Fondos / Aprobado / Saldo), botón "Ver caso" + acción principal contextual (Pedir firma, Liquidación, Cerrar), menú `···`
  - Gastos: card con merchant + badge review_status, empleado + fecha, monto destacado + score, checkbox táctil de selección, botón "Aprobar" + menú `···` (Rechazar, Observar), "Ver detalle"
  - Filtros de Casos apilados verticalmente en mobile (`flex-col` → `sm:flex-row`), selects a ancho completo con dos en fila
  - Batch action bar de Gastos rediseñado: contador + X en fila superior, botones en fila inferior con `flex-wrap`
  - Sin cambios en `DataTable`, `Shell` ni componentes compartidos; lógica de negocio y handlers intactos
  - Build limpio, TypeScript sin errores

- [x] **Historial de conversación como contexto del LLM en WhatsApp**
  - El LLM ahora recibe el historial de la conversación (últimos 10 turnos) además del contexto live del caso
  - `chat_whatsapp_with_context` acepta parámetro `history` y lo incluye en el array de mensajes al LLM
  - `chat_whatsapp_conversational` convierte el `message_log` (formato `speaker`/`text`) al formato OpenAI (`role`/`content`)
  - `handle_text_message` extrae el historial del contexto (excluyendo el mensaje actual, que ya fue logueado) y lo pasa al LLM
  - Centros de costo, presupuesto, gastos rendidos y saldo restante siempre frescos desde Sheets (sin cambios)

- [x] **Alerta de solicitud de asistencia humana**
  - Detección de frases de asistencia humana en `_handle_text_message` (`app/main.py`): keywords como "quiero hablar con un humano", "necesito asistencia humana", etc.
  - Al detectar la solicitud, se actualiza el campo `human_assistance_requested = True` en el caso activo vía `sheets_service.update_expense_case`
  - El bot responde confirmando que un operador fue notificado
  - En `send_conversation_message` (`app/api/backoffice.py`): al enviar un mensaje como operador, se limpia el flag (`human_assistance_requested = False`)
  - Frontend: banner de alerta naranja en el detalle del caso cuando `human_assistance_requested = True`
  - Frontend: badge "Asistencia solicitada" en la lista de rendiciones (vista mobile y tabla desktop)
  - `ChatPanel` recibe callback `onMessageSent` para refrescar el caso tras enviar mensaje y desactivar la alerta visualmente

### Pendiente

- [x] **PDF consolidado con balance final**
  - Reporte PDF descargable desde el detalle de rendición
  - Incluye balance final (fondos entregados vs rendido) y listado de documentos

- [x] **Quitar ayudante IA de la vista de rendición**
  - Remover el panel/entrada del ayudante IA en el detalle del caso/rendición
  - Mantener visibles las secciones operativas: balance, acciones, documentos, actividad y conversación
  - Revisar que el endpoint de chat de caso no quede expuesto desde esa vista si ya no se usa

- [x] **Mostrar conversación completa en el chat del backoffice**
  - En el chat visible desde backoffice, cargar y renderizar todo el historial disponible de la conversación
  - Evitar truncar a los últimos mensajes en la vista de detalle de rendición y en `/conversations/[phone]`
  - Mantener scroll automático al último mensaje sin impedir revisar mensajes antiguos

- [x] **Historial de auditoría**
  - Log persistente de quién aprobó/rechazó qué y cuándo
  - Requiere columna de audit_log o tabla separada
