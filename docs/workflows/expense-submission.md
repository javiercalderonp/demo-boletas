# Workflow De Rendición

Documento funcional base para implementar el flujo de rendición de forma consistente en backend, frontend y WhatsApp.

## Objetivo

Separar explícitamente cuatro cosas que hoy están parcialmente mezcladas:

- estado del documento individual
- estado de revisión del documento
- estado del caso de rendición
- estado de liquidación financiera

La intención es que el sistema pueda responder correctamente preguntas como:

- ¿el trabajador ya terminó de subir boletas?
- ¿backoffice ya revisó todo?
- ¿el caso ya quedó confirmado documentalmente?
- ¿la empresa le debe dinero al trabajador o al revés?
- ¿el caso está completamente cerrado o solo parcialmente?

## Principios

- Una rendición no requiere que todas las boletas estén aprobadas; requiere que todas estén resueltas.
- Un documento rechazado de forma definitiva no bloquea el cierre de revisión.
- Un documento observado o pendiente sí bloquea el avance del caso.
- El cierre documental y la liquidación financiera son etapas distintas.
- La modalidad de confirmación documental puede variar:
- con DocuSign
- con confirmación simple por WhatsApp
- La rendición solo queda completamente cerrada cuando ya no hay acciones documentales ni financieras pendientes.

## Capa 1: Estado Del Documento

Esta capa responde: "¿qué pasó finalmente con esta boleta?".

Estados propuestos:

- `pending_submission_review`
  - El documento fue guardado pero aún no fue resuelto por backoffice.
- `approved`
  - El documento fue aceptado y entra al cálculo final.
- `rejected_final`
  - El documento fue rechazado de forma definitiva y no entra al cálculo final.
- `awaiting_employee_input`
  - El documento necesita más antecedentes del trabajador.
- `internal_manual_review`
  - El documento necesita revisión interna del operador o empresa.

Reglas:

- `approved` cuenta como resuelto.
- `rejected_final` cuenta como resuelto.
- `awaiting_employee_input` no cuenta como resuelto.
- `internal_manual_review` no cuenta como resuelto.
- `pending_submission_review` no cuenta como resuelto.

Nota de migración:

- Hoy el sistema usa `status` y `review_status` con valores mezclados como `approved`, `rejected`, `observed`, `needs_manual_review`, `pending_approval`, `pending_review`.
- En la implementación posterior habrá que mapear esos valores al modelo canónico.

## Capa 2: Estado De Revisión Del Documento

Esta capa responde: "¿en qué situación de revisión está el documento ahora mismo?".

Estados propuestos:

- `pending_review`
  - Está esperando revisión humana o resolución final.
- `ready_to_approve`
  - El scoring lo deja bien posicionado para aprobación rápida.
- `observed`
  - El operador detectó que faltan antecedentes o corrección.
- `needs_manual_review`
  - Requiere criterio humano adicional.
- `resolved`
  - Ya quedó en una decisión final documental.

Relación entre capas:

- La capa de revisión ayuda a priorizar y operar.
- La capa de estado del documento representa el resultado final de negocio.
- No deben duplicarse sin intención.

## Regla Canónica De "Documento Resuelto"

Un documento se considera resuelto si y solo si su resultado final es uno de estos:

- `approved`
- `rejected_final`

Un documento no resuelto bloquea el avance del caso si está en cualquiera de estas condiciones:

- pendiente de revisión
- observado
- esperando antecedentes del trabajador
- en revisión manual interna

## Capa 3: Estado Del Caso De Rendición

Esta capa responde: "¿en qué etapa general del caso estamos?".

Estados propuestos:

- `collecting_receipts`
  - El trabajador todavía puede seguir subiendo boletas.
- `receipt_submission_closed`
  - El trabajador declaró que ya terminó de subir boletas.
  - Desde aquí no deberían entrar más documentos salvo reapertura.
- `review_in_progress`
  - Backoffice está revisando los documentos cargados.
- `review_blocked_waiting_employee`
  - Existe al menos un documento que requiere nueva acción del trabajador.
- `review_completed`
  - Todos los documentos quedaron resueltos.
- `document_confirmation_pending`
  - El caso ya está listo para confirmación documental.
  - Aquí aplica DocuSign o confirmación simple por WhatsApp.
- `financial_settlement_pending`
  - El caso ya fue confirmado documentalmente y falta ejecutar o registrar la liquidación.
- `fully_closed`
  - El caso quedó completamente cerrado, sin acciones documentales ni financieras pendientes.

## Reglas De Transición Del Caso

### 1. Carga de boletas

`collecting_receipts` -> `receipt_submission_closed`

Ocurre cuando:

- el trabajador indica que ya no subirá más boletas
- o el operador fuerza el cierre de carga

Efecto:

- se cierra la etapa de captura documental
- nuevas boletas no deberían aceptarse automáticamente

### 2. Inicio o continuación de revisión

`receipt_submission_closed` -> `review_in_progress`

Ocurre cuando:

- backoffice toma el caso para revisar los documentos cargados

### 3. Bloqueo por antecedentes faltantes

`review_in_progress` -> `review_blocked_waiting_employee`

Ocurre cuando:

- al menos un documento queda observado
- al menos un documento requiere nueva respuesta, respaldo o reenvío del trabajador

Salida de esta etapa:

- el trabajador responde o reenvía antecedentes
- los documentos vuelven a revisión y luego quedan resueltos

### 4. Cierre de revisión

`review_in_progress` -> `review_completed`

Ocurre solo si:

- no quedan documentos no resueltos

Regla obligatoria:

- no se puede avanzar mientras exista cualquier documento no resuelto

### 5. Confirmación documental

`review_completed` -> `document_confirmation_pending`

Ocurre cuando:

- el sistema prepara el consolidado y solicita confirmación formal del trabajador

Modalidades permitidas:

- `docusign`
- `whatsapp_simple_confirmation`

### 6. Confirmación recibida

`document_confirmation_pending` -> `financial_settlement_pending`

Ocurre cuando:

- el trabajador firma por DocuSign
- o el trabajador confirma explícitamente por WhatsApp

### 7. Cierre total

`financial_settlement_pending` -> `fully_closed`

Ocurre cuando:

- el balance quedó cuadrado sin acción adicional
- o se registró el reembolso al trabajador
- o se registró la devolución del trabajador a la empresa

## Capa 4: Estado De Liquidación Financiera

Esta capa responde: "¿cómo quedó la cuenta final entre trabajador y empresa?".

Estados propuestos:

- `balanced`
  - No existe deuda entre las partes.
- `company_owes_employee`
  - El monto aprobado supera los fondos entregados y la empresa debe reembolsar diferencia.
- `employee_owes_company`
  - Los fondos entregados superan el monto aprobado y el trabajador debe devolver diferencia.
- `settlement_pending`
  - Ya se calculó el resultado, pero falta ejecutar o registrar la acción financiera.
- `settled`
  - La acción financiera ya fue completada o no era necesaria.

## Regla De Cálculo Financiero

El cálculo final debe usar:

- `fondos_entregados`
- `monto_rendido_aprobado`

No debe usar:

- documentos observados
- documentos pendientes
- documentos rechazados

Fórmula:

- `neto = monto_rendido_aprobado - fondos_entregados`

Interpretación:

- `neto = 0` -> `balanced`
- `neto > 0` -> `company_owes_employee`
- `neto < 0` -> `employee_owes_company`

## Modos De Confirmación Documental

El sistema debe soportar dos variantes equivalentes de cierre documental:

### Opción A: DocuSign

- se genera PDF consolidado
- se envía link de firma
- la aceptación queda registrada vía DocuSign

### Opción B: Confirmación simple por WhatsApp

- se envía resumen consolidado por chat
- el trabajador confirma explícitamente en el chat
- la aceptación queda trazada con mensaje, fecha y usuario

Regla:

- la modalidad elegida no cambia el cálculo de liquidación
- solo cambia la forma de dejar constancia de la aceptación documental

## Reglas De Bloqueo Obligatorias

No se puede pasar a `review_completed`, `document_confirmation_pending` o `financial_settlement_pending` si:

- existe algún documento no resuelto
- existe al menos un documento esperando antecedentes del trabajador
- existe al menos un documento en revisión manual interna

No se puede pasar a `fully_closed` si:

- todavía falta registrar la liquidación financiera
- existe una devolución o reembolso pendiente

Estas reglas deben validarse en backend, no solo en frontend.

## Notificaciones Requeridas

### Cambios de documento

Cuando un documento cambie de estado:

- notificar al trabajador por WhatsApp
- idealmente como reply a la imagen original cuando el proveedor lo permita

Casos mínimos:

- aprobado
- rechazado definitivo
- observado / falta información
- enviado a revisión manual si corresponde informar

### Cierre de revisión

Cuando todos los documentos del caso queden resueltos:

- enviar resumen del caso
- informar que termina la etapa de revisión
- iniciar confirmación documental

### Resultado financiero

Una vez calculado el resultado:

- si `balanced`, informar que la rendición quedó cuadrada
- si `company_owes_employee`, informar que existe reembolso pendiente a favor del trabajador
- si `employee_owes_company`, informar que existe devolución pendiente a favor de la empresa

### Resolución de liquidación

Cuando el resultado no está cuadrado, la rendición no debería cerrarse solo con el cálculo.

Caso `employee_owes_company`:

- enviar al trabajador el monto a devolver
- incluir datos bancarios de la empresa
- pedir comprobante de depósito o transferencia por WhatsApp
- registrar ese comprobante como documento de liquidación, separado de las boletas del caso
- ejecutar validación automática con OCR + LLM
- si la confianza es alta y el comprobante coincide con monto, empresa y fecha esperada, marcar liquidación como resuelta
- si la confianza es baja o hay diferencias, derivar a revisión manual

Caso `company_owes_employee`:

- informar al trabajador que la empresa debe reembolsar
- dejar la liquidación en estado pendiente hasta que el operador registre el pago
- idealmente adjuntar o registrar comprobante de transferencia emitido por la empresa
- notificar al trabajador cuando el pago quede marcado como enviado
- cerrar la liquidación solo cuando exista confirmación operativa suficiente

Estados operativos sugeridos para esta etapa:

- `pending_employee_payment_proof`
- `payment_proof_under_review`
- `pending_company_payment`
- `company_payment_sent`
- `settled`

## Qué Existe Hoy Vs Qué Falta

### Existe hoy

- captura de boletas por WhatsApp
- OCR y validación conversacional
- revisión individual por backoffice
- generación de PDF consolidado
- integración DocuSign
- cálculo visible de `fondos_entregados`, `monto_rendido_aprobado`, `monto_pendiente_revision`, `saldo_restante`

### Falta formalizar o implementar

- separar claramente las cuatro capas de estado
- definir una regla canónica de documento resuelto
- bloquear el avance del caso por documentos no resueltos
- modelar la fase `review_blocked_waiting_employee`
- soportar cierre documental simple por WhatsApp
- modelar y persistir la liquidación financiera final
- formalizar la recepción y validación de comprobantes de liquidación
- distinguir cierre documental de cierre total

## Decisiones Que Deben Mantenerse En La Implementación

- Un documento rechazado definitivo no bloquea el caso.
- Un documento observado sí bloquea el caso.
- La firma o confirmación documental no equivale a liquidación financiera.
- Un caso solo queda totalmente cerrado cuando también quedó financieramente resuelto.
