# Code Review - demo-boletas

Fecha: 2026-05-07

## Verificacion ejecutada

- `python3 -m pytest`: 92 passed, 22 warnings.
- `npm run build` en `backoffice/`: build productivo exitoso.
- `npm run lint` en `backoffice/`: falla porque `next lint` abre un prompt interactivo de configuracion.

## Hallazgos

### Critico - Jobs y OAuth de DocuSign quedan expuestos si falta configuracion

Los endpoints internos validan `X-Scheduler-Token` solo cuando `SCHEDULER_ENDPOINT_TOKEN` esta configurado. Si la variable queda vacia, los jobs aceptan llamadas anonimas. Ademas, `/jobs/docusign/oauth/exchange` no tiene ninguna proteccion y devuelve `access_token` y `refresh_token` en la respuesta.

Evidencia:

- `app/config.py:121-122` deja `scheduler_endpoint_token` por defecto en `""`.
- `app/main.py:294-319` intercambia y retorna tokens DocuSign sin autenticacion.
- `app/main.py:321-377` protege jobs solo con `if configured_token and ...`.

Impacto:

- Generacion de documentos, envio de firma, recordatorios y tokens DocuSign pueden ser disparados o exfiltrados por terceros si el servicio es publico y falta la variable.

Recomendacion:

- Hacer fail-closed: si el token requerido no esta configurado en ambientes no-dev, devolver 503 o abortar startup.
- Proteger `/jobs/docusign/oauth/exchange` con el mismo mecanismo o removerlo del runtime publico.
- No retornar tokens OAuth en responses; guardarlos en Secret Manager o en un flujo operacional controlado.

### Critico - Credenciales default y secreto HMAC inseguro para backoffice

El sistema puede crear un admin default `admin@example.com` / `admin123` si no hay usuarios, y el secreto HMAC default es `change-me`.

Evidencia:

- `app/config.py:132` usa `BACKOFFICE_AUTH_SECRET="change-me"` por defecto.
- `services/backoffice_auth_service.py:37-40` crea admin demo con password conocido.
- `app/main.py:112-117` ejecuta `ensure_default_admin()` al iniciar.

Impacto:

- En una hoja nueva, staging mal configurado o produccion sin env vars, el backoffice queda con credenciales conocidas y tokens firmados con secreto trivial.

Recomendacion:

- En `APP_ENV != dev`, abortar startup si falta `BACKOFFICE_AUTH_SECRET` fuerte o si se intenta crear admin demo.
- Mover el seed demo a un script explicito, no al arranque de la app.

### Alto - Validacion de firma de WhatsApp esta apagada por defecto

Meta y Twilio aceptan webhooks sin validar firma salvo que una variable active la validacion.

Evidencia:

- `app/config.py:50-60` define `TWILIO_VALIDATE_SIGNATURE` y `META_VALIDATE_SIGNATURE` con default `False`.
- `services/whatsapp_service.py:39-54` retorna `True` cuando la validacion esta desactivada.
- `docs/ARCHITECTURE.md:379` indica que la validacion Meta estaba desactivada en la config local observada.

Impacto:

- Cualquiera que conozca el endpoint podria simular mensajes de empleados, crear/alterar conversaciones y gatillar OCR, storage, LLM o respuestas WhatsApp.

Recomendacion:

- Activar validacion obligatoria en ambientes publicos.
- Hacer startup checks por proveedor: Meta requiere `META_APP_SECRET`; Twilio requiere `TWILIO_AUTH_TOKEN`.

### Alto - `GET /health` expone detalles operacionales sensibles

El health endpoint publico retorna presencia de claves, IDs de servicios, bucket, account IDs, modelo, env y metadata de deploy.

Evidencia:

- `app/main.py:156-187` incluye `openai_api_key_present`, `gcs_bucket_name`, `document_ai_processor_id`, `docusign_account_id`, `deploy_commit`, `deploy_time`, etc.

Impacto:

- Facilita reconocimiento de infraestructura y confirma integraciones/secretos disponibles.

Recomendacion:

- Separar `/health` publico minimalista de `/diagnostics` autenticado.
- En `/health`, retornar solo `status`, version publica y readiness basica no sensible.

### Alto - Webhook Meta hace procesamiento pesado dentro del request y marca duplicados antes de terminar

Para Meta, el flujo espera OCR/storage/LLM dentro del request (`await _run_media_processing_during_request`) y marca el `message_id` como procesado antes de completar. Si el procesamiento falla o el request se corta, Meta no tendra una ruta limpia de reintento porque el mensaje ya quedo marcado.

Evidencia:

- `app/main.py:1223-1224` marca el inbound como procesado antes de manejar media/texto.
- `app/main.py:1259-1264`, `1298`, `1331-1332` esperan procesamiento durante el webhook.
- `app/main.py:1068-1128` resetea estado ante error, pero no desmarca el `message_id`.

Impacto:

- Riesgo de timeouts/retries de Meta, perdida de comprobantes y peor latencia en picos.

Recomendacion:

- Responder 200 rapido y encolar trabajo en una cola durable.
- Marcar deduplicacion con estados (`received`, `processing`, `done`, `failed`) y permitir retry idempotente.

### Alto - No hay autorizacion por rol aunque la UI/documentacion lo prometen

El backend solo valida que exista un usuario activo. No hay checks de `role` para operaciones destructivas o sensibles.

Evidencia:

- `app/api/backoffice.py:79-99` `require_user` no evalua roles.
- Todas las rutas usan `Depends(require_user)` sin politica de permisos.
- `backoffice/app/landing/page.tsx:323` y `backoffice/app/privacy/policy/page.tsx:104` hablan de control por roles.

Impacto:

- Cualquier usuario activo puede crear/eliminar empleados, crear/cerrar rendiciones, aprobar/rechazar gastos, exportar CSV y enviar mensajes por WhatsApp.

Recomendacion:

- Definir permisos por rol (`admin`, `operator`, `viewer`) y aplicarlos en endpoints.
- Hacer que frontend oculte acciones, pero tratar el backend como fuente de verdad.

### Medio - Google Sheets se usa con escrituras read-modify-write no transaccionales

Las actualizaciones leen registros completos, mezclan payload y reescriben filas enteras. En conversaciones, `context_json` completo se reemplaza. Con webhooks, auto-refresh/backoffice y jobs concurrentes, esto puede perder mensajes, colas pendientes o cambios de estado.

Evidencia:

- `services/sheets_service.py:579-613` `_upsert_by_key` escribe filas completas.
- `services/sheets_service.py:1060-1088` `update_conversation` reescribe `context_json`.
- `app/main.py:2072-2131` manipula `pending_receipts` con lectura y escritura separadas.

Impacto:

- Condiciones de carrera y perdida silenciosa de datos bajo concurrencia.

Recomendacion:

- Migrar estado operacional a Postgres/Firestore o agregar versionado optimista por fila.
- Separar logs/eventos append-only de snapshots conversacionales.

### Medio - Conversion de moneda usa tasas hardcodeadas sin fecha ni fuente

La conversion CLP usa una tabla fija en codigo.

Evidencia:

- `utils/exchange_rate.py:3-14` define tasas estaticas para USD/PEN/CNY/EUR/CLP.
- `services/expense_service.py:1212-1225` persiste `total_clp` usando esa conversion.

Impacto:

- Saldos, limites y liquidaciones pueden quedar financieramente incorrectos.

Recomendacion:

- Persistir `exchange_rate`, `exchange_rate_date` y fuente.
- Configurar tasas por fecha o integracion con proveedor de FX.

### Medio - El frontend no maneja todos los errores de API y puede ocultar fallas parciales

La pagina de gastos no muestra error si falla la carga o una accion. Las acciones masivas usan `Promise.all`; si una falla, algunas pueden haber sido aplicadas y la UI solo sale del flujo sin explicar el estado. Los exports descargan el body aunque la respuesta sea 401/500.

Evidencia:

- `backoffice/app/expenses/page.tsx:140-152` carga sin `.catch`.
- `backoffice/app/expenses/page.tsx:191-202` ejecuta acciones sin manejo de error visible.
- `backoffice/app/expenses/page.tsx:225-243` batch con `Promise.all` sin resumen de parciales.
- `backoffice/app/cases/page.tsx:258-270` y `backoffice/app/expenses/page.tsx:126-138` exportan CSV sin revisar `response.ok`.

Impacto:

- Operadores pueden creer que una accion fallo o tuvo exito sin evidencia clara, especialmente en aprobaciones/rechazos.

Recomendacion:

- Centralizar estados de error/loading por pagina.
- Para batch, ejecutar con resultado por item y mostrar exitos/fallos.
- Validar `response.ok` antes de crear el blob de descarga.

### Medio - Tooling de lint no corre en CI/local de forma no interactiva

El script `npm run lint` invoca `next lint`, que en este proyecto abre un prompt de configuracion y termina con error.

Evidencia:

- `backoffice/package.json:9` define `"lint": "next lint"`.
- Ejecucion local: prompt "How would you like to configure ESLint?" y exit code 1.

Impacto:

- No hay verificacion automatica consistente de lint para el backoffice.

Recomendacion:

- Migrar a ESLint CLI con config versionada.
- Agregar `npm run lint` y `npm run build` a CI.

### Bajo - Dependencias no estan fijadas de forma reproducible

Python usa rangos abiertos `>=` y frontend usa `^` para dependencias clave.

Evidencia:

- `requirements.txt:1-9` usa `>=`.
- `backoffice/package.json:11-18` usa `^` en dependencias runtime.

Impacto:

- Builds futuros pueden cambiar comportamiento sin cambios de codigo.

Recomendacion:

- Fijar versiones o usar lockfile para Python.
- Revisar Renovate/Dependabot para upgrades controlados.

### Bajo - Uso de `datetime.utcnow()` deprecado

La suite pasa, pero emite warnings por `datetime.utcnow()`.

Evidencia:

- `utils/helpers.py:10-11`.
- `pytest`: 22 warnings de deprecacion.

Impacto:

- Ruido en tests y futura incompatibilidad.

Recomendacion:

- Cambiar a `datetime.now(timezone.utc)` y mantener salida ISO `Z`.

### Bajo - Archivos residuales en la raiz

Hay archivos vacios sin rol aparente.

Evidencia:

- `S`, `next`, `expense-backoffice@0.1.0` existen y `file` los reporta como empty.

Impacto:

- Ruido de repo y riesgo de confusion al automatizar scripts.

Recomendacion:

- Confirmar si son residuos locales y eliminarlos o agregarlos a `.gitignore` si los genera alguna herramienta.

## Notas positivas

- La suite backend actual esta sana: 92 tests pasan.
- El build Next.js productivo compila correctamente.
- `.env` y la credencial local de Google no aparecen trackeadas por Git.
- Hay compatibilidad explicita con nombres legacy (`Trips`, `TripDocuments`) y tests para varios servicios criticos.

## Prioridad sugerida

1. Cerrar exposicion de jobs/OAuth, admin default, secreto HMAC y firmas WhatsApp.
2. Sacar procesamiento pesado del webhook Meta hacia cola durable o worker idempotente.
3. Agregar roles reales en backend.
4. Reducir datos expuestos en `/health`.
5. Mejorar resiliencia del frontend ante errores y batch parciales.
6. Planificar reemplazo de Google Sheets o controles de concurrencia.
