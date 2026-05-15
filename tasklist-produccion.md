# Tasklist — Preparación para Producción

> Generado en base a code review completo. Organizado por prioridad y área.

---

## 🔴 Crítico — Bloquea producción

### Seguridad

- [ ] **Habilitar validación de firma Meta (WhatsApp)**
  - `META_VALIDATE_SIGNATURE=false` en `.env` Y `default=False` en `config.py` — cualquiera puede hacer POST a `/webhook` haciéndose pasar por Meta.
  - En Cloud Run: setear `META_VALIDATE_SIGNATURE=true` y configurar `META_APP_SECRET` (el App Secret del panel de Meta Developers).
  - Archivo: `services/whatsapp_service.py:validate_meta_signature`, `app/config.py:59`

- [ ] **Setear `BACKOFFICE_AUTH_SECRET` con un valor seguro**
  - No está en el `.env` local. El default en `config.py` es `"change-me"`.
  - Todos los tokens JWT del backoffice se firman con ese secreto. Si alguien lo conoce, puede forjar tokens de cualquier usuario.
  - Generar con `python -c "import secrets; print(secrets.token_hex(32))"` y subir a Secret Manager.
  - Archivo: `app/config.py:132`, `services/backoffice_auth_service.py:139`

- [ ] **Eliminar credenciales de admin por defecto (`admin@example.com` / `admin123`)**
  - Si no hay usuarios en la hoja y `BACKOFFICE_DEFAULT_ADMIN_EMAIL` no está seteado, el sistema crea automáticamente un admin con password `admin123`.
  - En producción esto es una puerta trasera. Asegurarse de que `BACKOFFICE_DEFAULT_ADMIN_EMAIL` y `BACKOFFICE_DEFAULT_ADMIN_PASSWORD` estén seteados con valores seguros en Cloud Run, o modificar `ensure_default_admin()` para no crear el fallback en `APP_ENV=prod`.
  - Archivo: `services/backoffice_auth_service.py:38-41`

- [ ] **Setear `DEBUG=false` y `APP_ENV=prod` en Cloud Run**
  - Con `DEBUG=true`, FastAPI retorna stack traces completos en errores 500 al cliente (línea 683 de `main.py`). Además los endpoints `/test/simulate` y `/test/reset` se exponen públicamente.
  - Verificar en Cloud Run env vars que `APP_ENV=prod` y `DEBUG=false` estén seteados correctamente.
  - Archivo: `app/main.py:683`, `app/config.py:22`

- [ ] **Deshabilitar Swagger UI / ReDoc / OpenAPI en producción**
  - FastAPI expone `/docs`, `/redoc` y `/openapi.json` por defecto. En producción esto documenta todos los endpoints, schemas y parámetros a cualquier visitante.
  - Cambiar `create_app()` para deshabilitar en prod:
    ```python
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
    )
    ```
  - Archivo: `app/main.py:148`

---

## 🟠 Alto — Debe resolverse antes de go-live

### Seguridad

- [ ] **Agregar rate limiting al endpoint de login**
  - `/api/auth/login` no tiene ningún límite de intentos. Un atacante puede hacer fuerza bruta sin restricciones.
  - Agregar `slowapi` o similar al proyecto, o implementar un contador en memoria/Redis por IP+email.
  - Archivo: `app/api/backoffice.py:417`

- [ ] **Proteger endpoints `/jobs/*` cuando no hay `SCHEDULER_ENDPOINT_TOKEN`**
  - Los endpoints `/jobs/reminders/run`, `/jobs/documents/consolidated/generate` y `/jobs/documents/signature/start` usan el patrón:
    ```python
    if configured_token and x_scheduler_token != configured_token:
    ```
  - Si el token no está configurado, cualquiera puede llamar estos endpoints sin autenticación. Cambiar a: si no hay token configurado en `APP_ENV=prod`, rechazar la request.
  - Archivo: `app/main.py:388`, `app/main.py:402`, `app/main.py:437`

- [ ] **Eliminar `http://localhost:3000` del CORS en producción**
  - El código siempre agrega `http://localhost:3000` a los orígenes permitidos incluso en producción. Aunque CORS es solo enforcement de browser, es una práctica incorrecta.
  - Hacer que los orígenes locales solo se agreguen si `settings.debug` es True.
  - Archivo: `app/main.py:158-165`

- [ ] **No exponer información interna en errores de excepción**
  - Varios endpoints hacen `raise HTTPException(status_code=400, detail=str(exc))` que expone mensajes internos de Python al cliente. Revisar y reemplazar con mensajes genéricos en prod.
  - Archivo: `app/main.py:412`, `app/main.py:521`, y otros

### Configuración

- [ ] **Cambiar DocuSign de sandbox a producción**
  - `DOCUSIGN_BASE_URL=https://demo.docusign.net/restapi` está seteado en `.env`. Para producción usar `https://na4.docusign.net/restapi` (o el subdomain correcto de tu cuenta).
  - Archivo: `app/config.py:88`, `.env:52`

- [ ] **Configurar `NEXT_PUBLIC_API_BASE_URL` en Vercel en lugar de hardcodear la URL**
  - La URL de producción del backend está hardcodeada en `lib/api.ts:4`. Si cambia el servicio de Cloud Run, hay que redesplegar el frontend.
  - Setear `NEXT_PUBLIC_API_BASE_URL` como environment variable en Vercel apuntando al backend.
  - Archivo: `backoffice/lib/api.ts:4`

---

## 🟡 Medio — Importante para estabilidad y operación

### Observabilidad

- [ ] **Configurar logging estructurado y nivel de log en producción**
  - El backend usa `logger.warning()` para eventos normales de negocio (recepción de webhooks, procesamiento de boletas) lo cual satura el nivel WARNING. Revisar y usar `logger.info()` donde corresponde.
  - Considerar agregar un log handler estructurado (JSON) para facilitar búsquedas en Cloud Logging.
  - Archivo: `app/main.py:763`, `app/main.py:776`, etc.

- [ ] **Implementar audit log para acciones del backoffice**
  - No hay registro de quién aprobó, rechazó o modificó un gasto o rendición. En producción esto es necesario para trazabilidad y cumplimiento.
  - Considerar agregar una hoja "AuditLog" en Sheets con: timestamp, user_email, action, resource_type, resource_id, details.

- [ ] **Agregar alertas de error crítico**
  - Configurar alertas en Cloud Monitoring o un servicio externo (Sentry, etc.) para errores 500 y para fallos de integración críticos (Meta token expirado, Sheets inaccesible).

### Seguridad

- [ ] **Fortalecer requisitos de contraseña**
  - El único requisito es `min_length=8`. Para producción agregar validación de al menos una mayúscula, un número y un carácter especial.
  - Archivo: `app/schemas/backoffice.py:26`, `services/backoffice_auth_service.py:hash_password`

- [ ] **Rotar / eliminar el archivo JSON de service account del directorio del proyecto**
  - `viaticos-488419-1073823ba21a.json` existe en la raíz del proyecto con la clave privada. Está en `.gitignore` y nunca fue commiteado, pero es un riesgo si alguien tiene acceso al filesystem. Moverlo a un directorio fuera del proyecto o eliminarlo si ya no es necesario (Cloud Run usa ADC).

- [ ] **Habilitar validación de firma Twilio si se usa**
  - `TWILIO_VALIDATE_SIGNATURE=false` en `.env`. Si se usa el proveedor Twilio en producción, habilitarlo.
  - Archivo: `services/whatsapp_service.py:validate_incoming_request`, `app/config.py:50`

### Estabilidad

- [ ] **Evaluar límites de Google Sheets como base de datos en producción**
  - La API de Google Sheets tiene cuota de 300 requests por minuto por proyecto. Con uso concurrente (varios usuarios en backoffice + webhooks de WhatsApp) se puede alcanzar fácilmente.
  - El servicio tiene cacheo y cooldown implementados (`GOOGLE_SHEETS_READ_COOLDOWN_SECONDS`), pero evaluar si la carga esperada cabe dentro de los límites.
  - Considerar migrar a una base de datos real (Cloud SQL, Firestore) si el volumen lo justifica.

- [ ] **Definir política de retención y backup de datos en Sheets**
  - No hay backup automático de los datos en Google Sheets. Configurar exportación periódica o habilitar "Version history" en la hoja.

- [ ] **Validar manejo de tokens Meta expirados en producción**
  - El servicio captura `MetaAccessTokenExpiredError` pero no tiene un flujo automático de refresh del token de Meta. Cuando expire, las respuestas al usuario fallarán silenciosamente. Configurar alerta o proceso de renovación.
  - Archivo: `services/whatsapp_service.py`, `app/main.py`

---

## 🔵 Menor — Mejoras de calidad

- [ ] **Reemplazar implementación JWT custom por una librería estándar**
  - El sistema usa una implementación propia de tokens firmados (no es JWT estándar). Funciona correctamente, pero el uso de `PyJWT` o `python-jose` facilita la auditoría y el mantenimiento.
  - Archivo: `services/backoffice_auth_service.py:create_access_token`, `verify_access_token`

- [ ] **Agregar request ID / correlation ID en logs**
  - Los logs no tienen un ID de request que permita correlacionar todas las operaciones de un mismo webhook/petición. Agregar middleware que genere un UUID por request y lo incluya en todos los logs.

- [ ] **Revisar TTL de tokens de backoffice**
  - El token tiene TTL de 8 horas (`BACKOFFICE_TOKEN_TTL_SECONDS=28800`) y no hay refresh token. Cuando expira, el usuario es deslogueado abruptamente. Considerar implementar refresh token o extender la sesión en cada request activo.
  - Archivo: `app/config.py:133`

- [ ] **Agregar validación de formato E.164 en endpoints que reciben `phone`**
  - Los endpoints de backoffice aceptan `phone` como string sin validar que sea un número en formato E.164. Un valor inválido puede causar comportamientos inesperados en Sheets.
  - Archivo: `app/schemas/backoffice.py:EmployeePayload`, `app/api/backoffice.py`

- [ ] **Agregar `Content-Security-Policy` y headers de seguridad al frontend**
  - El backoffice no configura headers de seguridad HTTP (CSP, X-Frame-Options, etc.). Configurarlos en `next.config.js`.

---

## ✅ Confirmado OK

- **Firma de Meta webhook**: el código de `_handle_meta_webhook` sí valida la firma antes de procesar (línea 1236 de `main.py`). El problema es que la validación **está deshabilitada** por configuración (`META_VALIDATE_SIGNATURE=false`).
- **Hashing de contraseñas**: usa `pbkdf2_hmac` con 120,000 iteraciones y salt aleatorio. Correcto.
- **Comparación de tokens/hashes**: usa `hmac.compare_digest` para evitar timing attacks. Correcto.
- **Escaping HTML**: el callback de DocuSign y los XML de Twilio hacen `html.escape()` correctamente.
- **Credenciales de SA nunca commiteadas**: el archivo `.json` de service account está en `.gitignore` y no aparece en el historial de git.
- **Deduplicación de mensajes WhatsApp**: implementada con `processed_message_ids` por conversación (máx 50 IDs).
- **Token del scheduler**: si está configurado, se valida correctamente. El problema es el comportamiento cuando **no** está configurado.
- **BACKOFFICE_DEFAULT_ADMIN_PASSWORD**: está seteado en el `.env` (no usa el fallback `admin123` en local). Verificar que esté seteado en Cloud Run.
- **Redirección de firma DocuSign**: usa 307 (temporary redirect) correctamente, no 301.
- **Archivos de test en producción**: los endpoints `/test/simulate` y `/test/reset` ya validan `if not settings.debug` antes de ejecutar.

---

## 📋 Verificaciones de entorno antes de deploy final

- [ ] Confirmar que en Cloud Run estén seteados: `META_VALIDATE_SIGNATURE=true`, `META_APP_SECRET`, `BACKOFFICE_AUTH_SECRET`, `DEBUG=false`, `APP_ENV=prod`
- [ ] Confirmar que `BACKOFFICE_DEFAULT_ADMIN_EMAIL` y `BACKOFFICE_DEFAULT_ADMIN_PASSWORD` estén en Secret Manager (no usar el fallback `admin123`)
- [ ] Probar el flujo completo de login en el backoffice de producción
- [ ] Verificar que el webhook de Meta responde 200 con firma válida y 403 con firma inválida
- [ ] Confirmar que los endpoints de scheduler requieren token
- [ ] Verificar que `/docs`, `/redoc` y `/openapi.json` retornan 404 en producción
- [ ] Verificar que el DocuSign apunte a producción (no al sandbox `demo.docusign.net`)
- [ ] Confirmar Cloud Run min-instances=1 para evitar cold start en webhooks de WhatsApp
