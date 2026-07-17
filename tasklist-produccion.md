# Tasklist — Preparación para Producción

> Generado en base a code review completo. Organizado por prioridad y área.

---

## 🔴 Crítico — Bloquea producción

### Seguridad

- [x] **Habilitar validación de firma Meta (WhatsApp)**
  - `META_VALIDATE_SIGNATURE=true` en `.env` local y `default=True` en `config.py`.
  - Se agregaron tests para firma `sha256=` válida, firma inválida/faltante y falta de `META_APP_SECRET`.
  - Pendiente operativo: confirmar en Cloud Run `META_VALIDATE_SIGNATURE=true` y `META_APP_SECRET` con el App Secret real de Meta Developers.
  - Archivo: `services/whatsapp_service.py:validate_meta_signature`, `app/config.py:59`

- [ ] **Setear `BACKOFFICE_AUTH_SECRET` con un valor seguro**
  - El código ya falla cerrado si `BACKOFFICE_AUTH_SECRET` falta, mide menos de 32 caracteres o usa valores inseguros conocidos.
  - Pendiente operativo: generar con `python3 -c "import secrets; print(secrets.token_hex(32))"` y subir a Secret Manager/Cloud Run.
  - Archivo: `app/config.py:132`, `services/backoffice_auth_service.py:_auth_secret`

- [x] **Eliminar credenciales de admin por defecto (`admin@example.com` / `admin123`)**
  - `ensure_default_admin()` ya no crea ningún usuario si no se configuran credenciales explícitas.
  - Si se configura solo email o solo password, falla con `RuntimeError` para evitar estados ambiguos.
  - Pendiente operativo: confirmar que `BACKOFFICE_DEFAULT_ADMIN_EMAIL` y `BACKOFFICE_DEFAULT_ADMIN_PASSWORD` estén seteados con valores seguros en Cloud Run si se quiere bootstrap automático.
  - Archivo: `services/backoffice_auth_service.py:ensure_default_admin`, `tests/test_backoffice_auth_service.py`

- [ ] **Setear `DEBUG=false` y `APP_ENV=prod` en Cloud Run**
  - Con `DEBUG=true`, FastAPI puede retornar detalles técnicos de errores al cliente. Los endpoints `/test/simulate` y `/test/reset` siguen siendo solo debug y ahora además requieren `X-Scheduler-Token`.
  - Verificar en Cloud Run env vars que `APP_ENV=prod` y `DEBUG=false` estén seteados correctamente.
  - Archivo: `app/main.py:683`, `app/config.py:22`

- [x] **Deshabilitar Swagger UI / ReDoc / OpenAPI en producción**
  - `create_app()` solo expone `/docs`, `/redoc` y `/openapi.json` cuando `settings.debug` es `True`.
  - Cubierto por test que verifica que las rutas no existan con `DEBUG=false`.
  - Archivo: `app/main.py:create_app`, `tests/test_backoffice_api.py`

---

## 🟠 Alto — Debe resolverse antes de go-live

### Seguridad

- [x] **Agregar rate limiting al endpoint de login**
  - `/api/auth/login` ahora aplica un contador en memoria por IP+email.
  - Bloquea temporalmente después de 5 intentos fallidos en 5 minutos y limpia el contador con login exitoso.
  - Cubierto por tests.
  - Archivo: `app/api/backoffice.py`, `tests/test_backoffice_api.py`

- [x] **Proteger endpoints internos con `SCHEDULER_ENDPOINT_TOKEN`**
  - `app/main.py` centraliza la validación en `_require_scheduler_token()` y usa `hmac.compare_digest`.
  - Los endpoints `/jobs/reminders/run`, `/jobs/documents/consolidated/generate`, `/jobs/documents/signature/start` y `/jobs/docusign/oauth/exchange` rechazan llamadas sin token configurado o con token inválido.
  - `/jobs/docusign/oauth/exchange` ya no retorna `access_token` ni `refresh_token` en la respuesta.
  - Los endpoints debug `/test/simulate` y `/test/reset` también requieren `X-Scheduler-Token`.
  - Los scripts `scripts/run_scheduler_job.sh` y `scripts/install_scheduler_cron.sh` fallan localmente si falta `SCHEDULER_ENDPOINT_TOKEN`.

- [x] **Eliminar `http://localhost:3000` del CORS en producción**
  - Los orígenes locales solo se agregan si `settings.debug` es `True`.
  - Cubierto por tests para modo debug y producción.
  - Archivo: `app/main.py:create_app`, `tests/test_backoffice_api.py`

- [x] **No exponer información interna en errores de excepción**
  - Varios endpoints hacen `raise HTTPException(status_code=400, detail=str(exc))` que expone mensajes internos de Python al cliente. Revisar y reemplazar con mensajes genéricos en prod.
  - Se reemplazaron los casos de `detail=str(exc)` por mensajes controlados y logs internos. Los conflictos de negocio `ValueError` del backoffice conservan mensajes de validación esperados por la UI.
  - Verificado con `rg -n "detail=str\\(" app`.
  - Archivo: `app/main.py`, `app/api/backoffice.py`

### Configuración

- [ ] **Cambiar DocuSign de sandbox a producción**
  - `DOCUSIGN_BASE_URL=https://demo.docusign.net/restapi` está seteado en `.env`. Para producción usar `https://na4.docusign.net/restapi` (o el subdomain correcto de tu cuenta).
  - Archivo: `app/config.py:88`, `.env:52`

- [ ] **Configurar `NEXT_PUBLIC_API_BASE_URL` en Vercel en lugar de hardcodear la URL**
  - El hardcode de la URL productiva fue eliminado de `backoffice/lib/api.ts`.
  - En entornos no locales, el frontend ahora exige `NEXT_PUBLIC_API_BASE_URL`.
  - Pendiente operativo: setear `NEXT_PUBLIC_API_BASE_URL` en Vercel/Cloud Run apuntando al backend.
  - Archivo: `backoffice/lib/api.ts`

---

## 🟡 Medio — Importante para estabilidad y operación

### Observabilidad

- [x] **Configurar logging estructurado y nivel de log en producción**
  - Se agregó `LOG_LEVEL` y `LOG_FORMAT` a configuración.
  - En `APP_ENV=prod`, el formato por defecto es JSON para facilitar búsquedas en Cloud Logging.
  - Los logs incluyen `request_id` cuando hay contexto HTTP.
  - Archivo: `app/config.py`, `app/logging_config.py`, `app/main.py`

- [x] **Implementar audit log para acciones del backoffice**
  - Se agregó hoja `AuditLog` con `timestamp`, `user_email`, `action`, `resource_type`, `resource_id`, `company_id` y `details`.
  - Las acciones de usuarios, empleados, rendiciones, gastos y conversaciones registran auditoría después de completarse.
  - Cubierto por tests de API y `SheetsService`.
  - Archivo: `services/sheets_service.py`, `app/api/backoffice.py`, `tests/test_backoffice_api.py`, `tests/test_sheets_service.py`

- [ ] **Agregar alertas de error crítico**
  - Configurar alertas en Cloud Monitoring o un servicio externo (Sentry, etc.) para errores 500 y para fallos de integración críticos (Meta token expirado, Sheets inaccesible).

### Seguridad

- [x] **Fortalecer requisitos de contraseña**
  - El setup de contraseña exige mínimo 8 caracteres, una mayúscula, un número y un carácter especial.
  - La contraseña del admin bootstrap vía env vars también pasa por la misma validación.
  - Cubierto por tests.
  - Archivo: `app/schemas/backoffice.py`, `services/backoffice_auth_service.py`, `tests/test_backoffice_auth_service.py`

- [x] **Rotar / eliminar el archivo JSON de service account del directorio del proyecto**
  - Se eliminó `viaticos-488419-1073823ba21a.json` de la raíz del proyecto.
  - Cloud Run debe usar ADC/service account asociada al servicio; si esa key estuvo expuesta fuera de este equipo, rotarla también en GCP IAM.

- [ ] **Habilitar validación de firma Twilio si se usa**
  - `TWILIO_VALIDATE_SIGNATURE=false` en `.env`. Si se usa el proveedor Twilio en producción, habilitarlo.
  - Archivo: `services/whatsapp_service.py:validate_incoming_request`, `app/config.py:50`

### Estabilidad

- [x] **Evaluar límites de Google Sheets como base de datos en producción**
  - Se implementó backend SQLite persistente opcional con `PERSISTENCE_BACKEND=sqlite` y `SQLITE_DATABASE_PATH`.
  - El backend ya no depende operativamente de cuotas/rate limits de Google Sheets para demo/local.
  - Google Sheets queda como compatibilidad; Postgres/Cloud SQL queda como siguiente paso para alta concurrencia multi-instancia.

- [x] **Definir política de retención y backup de datos en Sheets**
  - Para el backend SQLite, usar `scripts/backup_sqlite.py` y copiar el backup timestamped a storage privado o al sistema de backups del ambiente.
  - Si se mantiene Google Sheets como compatibilidad, usar Version History/export periódico del spreadsheet.

- [ ] **Validar manejo de tokens Meta expirados en producción**
  - El servicio captura `MetaAccessTokenExpiredError` pero no tiene un flujo automático de refresh del token de Meta. Cuando expire, las respuestas al usuario fallarán silenciosamente. Configurar alerta o proceso de renovación.
  - Archivo: `services/whatsapp_service.py`, `app/main.py`

---

## 🔵 Menor — Mejoras de calidad

- [x] **Reemplazar implementación JWT custom por una librería estándar**
  - Los tokens nuevos usan `PyJWT` con HS256, `iat`, `exp` y `typ=access`.
  - Se mantiene compatibilidad temporal con tokens legacy de 2 segmentos para no cortar sesiones activas durante despliegue.
  - Cubierto por tests de emisión, expiración y fallback legacy.
  - Archivo: `services/backoffice_auth_service.py`, `requirements.txt`, `tests/test_backoffice_auth_service.py`

- [x] **Agregar request ID / correlation ID en logs**
  - Se agregó middleware HTTP que toma `X-Request-ID` si viene, o genera uno nuevo.
  - El ID se agrega a los logs mediante `contextvars` y se devuelve en el header `X-Request-ID`.
  - Archivo: `app/main.py`, `app/logging_config.py`

- [x] **Revisar TTL de tokens de backoffice**
  - Se agregó `POST /api/auth/refresh` para emitir un token nuevo si el token actual sigue válido.
  - El frontend refresca el token al restaurar sesión y cada 30 minutos mientras el usuario está activo.
  - Cubierto por tests de API y build de frontend.
  - Archivo: `app/api/backoffice.py`, `backoffice/components/auth-provider.tsx`, `tests/test_backoffice_api.py`

- [x] **Agregar validación de formato E.164 en endpoints que reciben `phone`**
  - `EmployeePayload.phone` y `CasePayload.employee_phone` validan formato E.164 estricto.
  - Cubierto por tests de payload.
  - Archivo: `app/schemas/backoffice.py`, `tests/test_backoffice_api.py`

- [x] **Agregar `Content-Security-Policy` y headers de seguridad al frontend**
  - `next.config.ts` ahora agrega CSP, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` y `Permissions-Policy`.
  - Archivo: `backoffice/next.config.ts`

---

## ✅ Confirmado OK

- **Firma de Meta webhook**: el código de `_handle_meta_webhook` valida la firma antes de procesar (línea 1236 de `main.py`) y la configuración local quedó activada (`META_VALIDATE_SIGNATURE=true`, default `True`).
- **Hashing de contraseñas**: usa `pbkdf2_hmac` con 120,000 iteraciones y salt aleatorio. Correcto.
- **Comparación de tokens/hashes**: usa `hmac.compare_digest` para evitar timing attacks. Correcto.
- **Escaping HTML**: el callback de DocuSign y los XML de Twilio hacen `html.escape()` correctamente.
- **Credenciales de SA nunca commiteadas**: el archivo `.json` de service account está en `.gitignore` y no aparece en el historial de git.
- **Deduplicación de mensajes WhatsApp**: implementada con `processed_message_ids` por conversación (máx 50 IDs).
- **Token del scheduler**: los endpoints internos ahora fallan cerrados cuando `SCHEDULER_ENDPOINT_TOKEN` no está configurado y rechazan tokens ausentes/incorrectos.
- **OAuth DocuSign interno**: `/jobs/docusign/oauth/exchange` requiere `X-Scheduler-Token` y no expone tokens OAuth completos en la respuesta.
- **Health público**: `/health` responde solo `{ "status": "ok" }`, sin detalles operacionales sensibles.
- **BACKOFFICE_DEFAULT_ADMIN_PASSWORD**: está seteado en el `.env` (no usa el fallback `admin123` en local). Verificar que esté seteado en Cloud Run.
- **Redirección de firma DocuSign**: usa 307 (temporary redirect) correctamente, no 301.
- **Archivos de test en producción**: los endpoints `/test/simulate` y `/test/reset` validan `if not settings.debug` antes de ejecutar y requieren `X-Scheduler-Token`.

---

## 📋 Verificaciones de entorno antes de deploy final

- [ ] Confirmar que en Cloud Run estén seteados: `META_VALIDATE_SIGNATURE=true`, `META_APP_SECRET`, `BACKOFFICE_AUTH_SECRET`, `DEBUG=false`, `APP_ENV=prod`
- [ ] Confirmar que `BACKOFFICE_DEFAULT_ADMIN_EMAIL` y `BACKOFFICE_DEFAULT_ADMIN_PASSWORD` estén en Secret Manager (no usar el fallback `admin123`)
- [ ] Probar el flujo completo de login en el backoffice de producción
- [ ] Verificar en Cloud Run que el webhook de Meta responde 200 con firma válida y 403 con firma inválida
- [ ] Confirmar que los endpoints de scheduler requieren token
- [ ] Verificar que `/docs`, `/redoc` y `/openapi.json` retornan 404 en producción
- [ ] Verificar que el DocuSign apunte a producción (no al sandbox `demo.docusign.net`)
- [ ] Confirmar Cloud Run min-instances=1 para evitar cold start en webhooks de WhatsApp
