# Expense Submission AI Agent (MVP v1)

MVP para automatizar la rendición de boletas, facturas y comprobantes vía WhatsApp, con captura de documentos, OCR, validación conversacional y almacenamiento estructurado en Google Sheets.

## Objetivo

Construir un agente de rendición de gastos por WhatsApp que:

- Reciba imágenes de boletas, facturas o comprobantes.
- Extraiga información con OCR.
- Converse con el usuario cuando falten datos.
- Registre gastos estructurados en Google Sheets.
- Mantenga seguimiento de documentos pendientes.
- Genere un documento consolidado para aprobación o firma posterior.

## Modelo de dominio

El proyecto fue generalizado desde un caso de viáticos/viajes hacia un modelo más estándar de rendición:

- `ExpenseCase`: contenedor de una rendición o caso de gasto.
- `Expense`: documento individual validado y registrado.
- `Conversation`: estado conversacional y borrador del gasto.
- `ExpenseCaseDocument`: PDF consolidado para cierre, aprobación o firma.

Para no romper el MVP, todavía existen aliases internos compatibles con nombres antiguos como `trip_id`, `Trips` o `TripDocuments`, pero el lenguaje preferido del sistema ahora es:

- `case_id`
- `ExpenseCases`
- `ExpenseCaseDocuments`
- `submission_closure`
- `ExpenseCaseService`

## Flujo principal

1. El usuario envía una imagen por WhatsApp.
2. El sistema ejecuta OCR e intenta extraer `merchant`, `date`, `total`, `currency`, `category`, `country` y `case_id`.
3. Si faltan datos, el bot pregunta uno por uno.
4. Cuando el borrador queda completo, envía un resumen para confirmar.
5. Al confirmar, guarda el gasto en `Expenses`.
6. Si corresponde, envía recordatorios de documentos pendientes y luego genera el consolidado para firma.

## Estados conversacionales

- `WAIT_RECEIPT`
- `PROCESSING`
- `NEEDS_INFO`
- `CONFIRM_SUMMARY`
- `DONE`
- `WAIT_SUBMISSION_CLOSURE_CONFIRMATION`

## Arquitectura

```text
app/
  main.py
  config.py

services/
  expense_case_service.py
  sheets_service.py
  whatsapp_service.py
  ocr_service.py
  expense_service.py
  conversation_service.py
  scheduler_service.py
  consolidated_document_service.py
  docusign_service.py
  storage_service.py
  llm_service.py
```

## Google Sheets

Hojas principales:

- `Employees`
- `ExpenseCases`
- `Expenses`
- `Conversations`
- `ExpenseCaseDocuments`

Campos relevantes:

- `ExpenseCases`: `case_id`, `phone`, `context_label`, `country`, `opened_at`, `due_date`, `policy_limit`, `status`
- `Expenses`: `expense_id`, `phone`, `case_id`, `merchant`, `date`, `currency`, `total`, `total_clp`, `category`, `country`, `status`
- `ExpenseCaseDocuments`: `document_id`, `phone`, `case_id`, `object_key`, `expense_count`, `total_clp`, `signature_status`

Notas:

- El servicio de Sheets mantiene compatibilidad con hojas legacy (`Trips`, `TripDocuments`) cuando ya existen.
- También conserva aliases como `trip_id` para no romper integraciones del MVP.

## Scripts útiles

- `scripts/seed_sheets.py`: crea headers y datos demo usando el modelo nuevo.
- `scripts/reset_test_state.py`: recrea un caso activo de prueba y limpia la conversación.
- `scripts/install_scheduler_cron.sh`: instala el job de recordatorios.

## Verificación

Prueba ejecutada durante este refactor:

```bash
PYTHONPYCACHEPREFIX=/tmp python3 -m unittest tests/test_receipt_pipeline.py
```

## Observaciones

- El scheduler ya no habla de “viajes”; ahora modela recordatorios de rendición y cierre de documentos pendientes.
- El consolidado PDF y la firma quedaron adaptados a un lenguaje general de rendición.
- Se conservaron algunos aliases legacy para minimizar riesgo y facilitar migración progresiva.
