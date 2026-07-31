# Cierre contable y exportación Excel — Porta

## 1. Objetivo

Este documento define el funcionamiento esperado del **cierre contable** en ExpenseOps para Porta.

El objetivo es que, una vez cerrado un caso de rendición, ExpenseOps pueda generar un archivo Excel compatible con el formato actualmente utilizado por el equipo de contabilidad de Porta.

La exportación debe construirse a partir de los gastos registrados y aprobados dentro del caso, respetando:

- La estructura del Excel entregado por Porta.
- Los seis centros de costo definidos para la empresa.
- Los campos contables y tributarios requeridos por cada tipo de gasto.
- Una cantidad dinámica e ilimitada de gastos.
- La posibilidad de exportar un caso individual o múltiples casos consolidados.

---

## 2. Distinción entre cierre del caso y cierre contable

ExpenseOps debe tratar como procesos independientes:

1. La **liquidación financiera del caso**.
2. La **exportación contable de los gastos**.

### 2.1. Liquidación financiera del caso

La liquidación determina la relación de dinero entre Porta y la persona responsable de la rendición.

Puede incluir:

- Fondos entregados inicialmente.
- Total de gastos aprobados.
- Monto que la persona debe devolver.
- Monto adicional que Porta debe transferir.
- Estado final de la rendición.

Ejemplo:

```text
Fondos entregados a la persona:     $1.000.000
Gastos aprobados:                     $850.000
Monto que debe devolver:              $150.000
```

### 2.2. Exportación contable

La exportación contable contiene los gastos efectivamente incurridos y respaldados por documentos.

En el ejemplo anterior, el Excel debe incluir solamente los **$850.000 de gastos aprobados**.

La transferencia inicial de $1.000.000 no debe registrarse como un gasto dentro de este Excel, ya que corresponde a una entrega o anticipo de fondos y no al gasto definitivo realizado por la empresa.

### 2.3. Regla principal

> El resultado financiero del caso no determina los gastos incluidos en el Excel. La exportación contable se construye exclusivamente a partir de los gastos aprobados del caso.

---

## 3. Alcance inicial para Porta

Para Porta existirán seis centros de costo disponibles en el flujo de rendición:

1. Gastos de producción.
2. Alimentación.
3. Combustible.
4. Estacionamientos, peajes y taxis.
5. Boletas de honorarios.
6. Facturas.

Cada centro de costo corresponde a una hoja específica del Excel.

| Centro de costo | Hoja de destino |
|---|---|
| Gastos de producción | `Gastos de Producción` |
| Alimentación | `Alimentación` |
| Combustible | `Combustible` |
| Estacionamientos, peajes y taxis | `Estacionamientos-Peajes-Taxis` |
| Boletas de honorarios | `Boletas de Honorarios` |
| Facturas | `Facturas` |

Aunque algunos de estos conceptos podrían considerarse categorías contables o tipos de documento, para el flujo de Porta se utilizará el término **centro de costo**, ya que es el concepto operativo utilizado por el cliente.

Internamente, el sistema debería mantener este dato en un campo independiente y configurable, por ejemplo:

```text
cost_center
```

Esto permitirá adaptar en el futuro la terminología o estructura de otras empresas sin modificar la lógica general del gasto.

---

## 4. Flujo de registro de un gasto

El flujo actual de reconocimiento debe mantenerse.

ExpenseOps no debe utilizar el OCR para decidir automáticamente el centro de costo.

### 4.1. Flujo esperado

```text
1. La persona envía una boleta, factura u otro documento.
2. ExpenseOps procesa el archivo mediante OCR.
3. ExpenseOps reconoce y muestra los datos detectados.
4. ExpenseOps pregunta explícitamente el centro de costo.
5. La persona selecciona uno de los seis centros de costo de Porta.
6. ExpenseOps solicita la confirmación del gasto.
7. El gasto se registra dentro del caso.
8. El administrador puede revisar y corregir la información desde el backoffice.
```

### 4.2. Ejemplo de interacción

```text
Recibí tu documento y reconocí lo siguiente:

Comercio: Copec
Fecha: 28/07/2026
Número de documento: 145829
Total: $62.500

¿A qué centro de costo corresponde este gasto?

1. Gastos de producción
2. Alimentación
3. Combustible
4. Estacionamientos, peajes y taxis
5. Boletas de honorarios
6. Facturas
```

Después de la selección:

```text
Centro de costo: Combustible

¿Confirmas el gasto por $62.500?

1. Confirmar
2. Editar información
3. Cambiar centro de costo
```

### 4.3. Regla de clasificación

> La hoja de destino del Excel debe determinarse exclusivamente a partir del centro de costo seleccionado por el usuario.

El OCR puede reconocer el tipo de documento para extraer correctamente los campos, pero no debe modificar, reemplazar ni seleccionar automáticamente el centro de costo.

---

## 5. Responsabilidades del OCR

El OCR debe intentar reconocer la mayor cantidad posible de información del documento.

### 5.1. Campos comunes

- Fecha del documento.
- Número del documento.
- Comercio, proveedor o emisor.
- RUT del emisor, cuando esté disponible.
- Descripción o detalle.
- Moneda.
- Total.
- Tipo de documento detectado.
- Imagen o archivo original.

### 5.2. Campos para facturas

- Número de factura.
- Neto.
- IVA.
- Total.
- RUT del emisor.
- RUT del receptor, cuando esté disponible.

### 5.3. Campos para boletas de honorarios

- Número de boleta.
- Prestador o emisor.
- RUT del prestador.
- Monto bruto.
- Retención.
- Monto líquido.

### 5.4. Centro de costo

El centro de costo no debe ser inferido automáticamente por el OCR.

Siempre debe solicitarse al usuario, incluso cuando el sistema reconozca que el documento parece ser una factura o una boleta de honorarios.

---

## 6. Datos que debe guardar cada gasto

Cada gasto debe conservar, como mínimo, los siguientes campos:

```text
expense_id
case_id
company_id
employee_id

document_type
cost_center

document_date
document_number
merchant
issuer_tax_id
receiver_tax_id
description
currency

total_amount
net_amount
tax_amount
gross_amount
withholding_amount
liquid_amount

approval_status
processing_status
export_status

receipt_storage_provider
receipt_object_key
source_message_id

created_at
updated_at
approved_at
approved_by
```

No todos los campos financieros se utilizan para todos los gastos.

| Tipo de registro | Campos financieros principales |
|---|---|
| Gasto general | `total_amount` |
| Factura | `net_amount`, `tax_amount`, `total_amount` |
| Boleta de honorarios | `gross_amount`, `withholding_amount`, `liquid_amount` |

### 6.1. Separación entre tipo de documento y centro de costo

El sistema debe conservar ambos campos por separado:

```text
document_type = "factura"
cost_center = "facturas"
```

Aunque para Porta normalmente ambos valores estarán relacionados, conceptualmente cumplen funciones distintas:

- `document_type` describe el documento reconocido.
- `cost_center` determina la clasificación elegida por el usuario y la hoja del Excel.

La exportación debe utilizar `cost_center` como regla de agrupación.

---

## 7. Reglas para facturas

Todas las facturas seleccionadas dentro del centro de costo `Facturas` deben ir a la hoja:

```text
Facturas
```

### 7.1. Campos de exportación

| Fecha | N.º documento | Detalle | Neto | IVA | Total |
|---|---|---|---:|---:|---:|

### 7.2. IVA

Para las facturas afectas, el IVA utilizado será de 19%.

El orden de prioridad debe ser:

1. Utilizar los valores explícitos del documento cuando sean reconocidos correctamente.
2. Calcular los valores faltantes utilizando IVA de 19%.
3. Permitir corrección manual desde el backoffice.

Cuando solo se conozca el total:

```text
Neto = Total / 1,19
IVA = Total - Neto
```

Cuando solo se conozca el neto:

```text
IVA = Neto × 0,19
Total = Neto + IVA
```

Los montos deben redondearse de acuerdo con la lógica utilizada por contabilidad en pesos chilenos.

### 7.3. Facturas exentas

Una factura exenta o no afecta es una factura válida que no incorpora IVA.

Ejemplo:

```text
Neto o monto exento: $100.000
IVA:                        $0
Total:                $100.000
```

No se requiere una hoja separada. En caso de soportarse, debe permanecer dentro de la hoja `Facturas`, con IVA igual a cero.

Para el alcance inicial se puede asumir que las facturas de Porta utilizan IVA de 19%, pero la implementación no debería impedir registrar una factura con IVA igual a cero si el documento lo indica explícitamente.

---

## 8. Reglas para boletas de honorarios

Las boletas de honorarios seleccionadas dentro del centro de costo correspondiente deben ir a la hoja:

```text
Boletas de Honorarios
```

### 8.1. Campos de exportación

| Fecha | N.º documento | Detalle | Líquido | Retención | Bruto |
|---|---|---|---:|---:|---:|

### 8.2. Orden de prioridad

El sistema debe:

1. Intentar reconocer el bruto directamente desde la boleta.
2. Intentar reconocer la retención.
3. Intentar reconocer el líquido.
4. Validar la consistencia de los valores.
5. Calcular solamente los valores faltantes.

La validación básica es:

```text
Bruto - Retención = Líquido
```

El porcentaje de retención utilizado como fallback no debe quedar fijo permanentemente en el código. Debe poder configurarse por empresa o período tributario.

Para Porta, el bruto normalmente será obtenido directamente desde la boleta.

---

## 9. Reglas para gastos generales

Los siguientes centros de costo utilizan la estructura general:

- Gastos de producción.
- Alimentación.
- Combustible.
- Estacionamientos, peajes y taxis.

### 9.1. Campos de exportación

| Fecha | N.º documento | Detalle | Total |
|---|---|---|---:|

El campo `Detalle` puede construirse a partir de:

1. La descripción ingresada o confirmada por el usuario.
2. El nombre del comercio o proveedor.
3. Una combinación de ambos, según la configuración definida para Porta.

---

## 10. Validación previa al cierre contable

Antes de generar el Excel, ExpenseOps debe validar que todos los gastos incluidos tengan información suficiente.

Solo deben incluirse gastos con estado aprobado.

### 10.1. Requisitos para gastos generales

- Fecha.
- Número de documento, cuando corresponda.
- Detalle.
- Total.
- Centro de costo.
- Estado aprobado.

### 10.2. Requisitos para facturas

- Fecha.
- Número de factura.
- Detalle o proveedor.
- Neto.
- IVA.
- Total.
- Centro de costo `Facturas`.
- Estado aprobado.

### 10.3. Requisitos para boletas de honorarios

- Fecha.
- Número de boleta.
- Detalle o prestador.
- Líquido.
- Retención.
- Bruto.
- Centro de costo `Boletas de honorarios`.
- Estado aprobado.

### 10.4. Gastos incompletos

Si existen gastos incompletos, el sistema debe mostrarlos claramente antes de generar el archivo.

Ejemplo:

```text
Hay 3 gastos con información contable incompleta:

- Factura 184: falta número de documento.
- Factura 192: no se pudo validar el IVA.
- Boleta de honorarios 31: falta monto bruto.
```

La primera versión puede impedir la generación hasta corregir los errores críticos.

Las advertencias no críticas pueden permitir continuar, siempre que queden registradas.

---

## 11. Generación del Excel por caso

Al cerrar un caso, ExpenseOps debe permitir generar un Excel individual.

### 11.1. Contenido

El archivo debe incluir:

- Solo gastos pertenecientes al caso.
- Solo gastos aprobados.
- Gastos distribuidos según el centro de costo seleccionado.
- Todos los campos requeridos por la hoja correspondiente.
- Fórmulas y totales actualizados.
- El mismo orden y formato utilizado por Porta.

### 11.2. Datos generales

Cuando corresponda al formato original, el sistema puede completar:

- Fecha de rendición.
- Nombre de la persona.
- Departamento.
- Proyecto.

Sin embargo, la prioridad funcional del primer alcance está en la correcta exportación de los gastos y sus columnas.

### 11.3. Nombre sugerido

```text
Rendicion_Porta_{persona}_{case_id}.xlsx
```

Ejemplo:

```text
Rendicion_Porta_Javier_Calderon_CASO-00123.xlsx
```

---

## 12. Generación de un Excel consolidado

ExpenseOps también debe permitir generar un archivo con gastos provenientes de múltiples casos de Porta.

### 12.1. Filtros sugeridos

- Empresa.
- Rango de fechas.
- Casos seleccionados.
- Estado del caso.
- Persona.
- Proyecto, cuando sea necesario.

### 12.2. Contenido

El archivo consolidado debe:

- Utilizar las mismas hojas y centros de costo.
- Incluir todos los gastos aprobados que cumplan los filtros.
- Mantener el formato de columnas esperado por contabilidad.
- Permitir copiar y pegar los datos sin transformación manual adicional.

### 12.3. Trazabilidad

Si Porta necesita mantener una compatibilidad estricta con las columnas actuales, no se deben agregar columnas visibles sin validación previa.

La trazabilidad puede mantenerse internamente mediante:

- ID del gasto.
- ID del caso.
- Persona.
- Fecha de cierre.
- Usuario que aprobó.
- Archivo de origen.
- Fecha de generación.

Esta información puede guardarse:

- En la base de datos.
- En metadatos asociados a la exportación.
- En una hoja oculta o adicional, si Porta lo aprueba.

---

## 13. Cantidad dinámica de gastos

La exportación no debe quedar limitada a la cantidad de filas visibles en la plantilla original.

Puede haber más de 27 gastos por hoja o por caso.

La implementación debe:

- Insertar dinámicamente todas las filas necesarias.
- Replicar el estilo de la plantilla.
- Mantener formatos de fecha y moneda.
- Extender fórmulas.
- Actualizar rangos de totales.
- Evitar sobrescribir filas de resumen.
- Mantener el archivo válido para Excel y Google Sheets.

No se deben utilizar rangos rígidos que limiten la cantidad de gastos.

Ejemplo de implementación incorrecta:

```text
Escribir únicamente entre A10 y F36
```

La generación debe basarse en una fila inicial de datos y agregar tantas filas como sea necesario.

---

## 14. Experiencia en el backoffice

En el detalle del caso deben existir dos secciones separadas.

### 14.1. Cierre financiero

Ejemplo:

```text
Fondos entregados:                 $1.000.000
Gastos aprobados:                    $850.000
Saldo a devolver por la persona:     $150.000
```

### 14.2. Exportación contable

Ejemplo:

```text
Formato: Porta — Rendición 2026
Gastos contables: 24
Monto total: $850.000
Estado: Listo para exportar
```

Acciones sugeridas:

- Vista previa.
- Descargar Excel.
- Regenerar archivo.
- Ver errores de validación.
- Ver historial de exportaciones.

### 14.3. Resumen por centro de costo

```text
Gastos de producción              7 gastos     $310.000
Alimentación                      5 gastos      $95.000
Combustible                       3 gastos     $120.000
Estacionamientos, peajes y taxis  4 gastos      $75.000
Boletas de honorarios             2 gastos     $150.000
Facturas                          3 gastos     $100.000
```

---

## 15. Estados de exportación

Cada caso puede manejar un estado de exportación contable independiente del estado financiero.

Estados sugeridos:

```text
not_ready
ready
generating
generated
generated_with_warnings
failed
```

Cada gasto también puede tener:

```text
not_exported
exported
export_error
```

El archivo generado debe quedar asociado al caso y conservar:

- Fecha de generación.
- Usuario que generó el archivo.
- Versión.
- Cantidad de gastos incluidos.
- Total exportado.
- Ruta o identificador del archivo.
- Errores o advertencias.
- Parámetros utilizados.

---

## 16. Regeneración y versionado

Si un gasto cambia después de haber generado el Excel, el sistema debe permitir regenerar la exportación.

No se debería sobrescribir silenciosamente un archivo anterior.

Cada generación debe crear una nueva versión, por ejemplo:

```text
v1 — generado al cerrar el caso
v2 — generado después de corregir una factura
v3 — generado después de actualizar una boleta de honorarios
```

La exportación más reciente puede marcarse como vigente.

Las versiones anteriores deben mantenerse disponibles para auditoría, al menos durante el período de retención definido por la empresa.

---

## 17. Reglas funcionales principales

1. La liquidación financiera y la exportación contable son procesos distintos.
2. La transferencia inicial a la persona no se exporta como gasto.
3. El Excel contiene exclusivamente gastos aprobados.
4. El OCR reconoce datos del documento, pero no decide el centro de costo.
5. El centro de costo siempre se pregunta al usuario.
6. Porta tiene seis centros de costo configurados.
7. El centro de costo determina la hoja de destino.
8. Las facturas utilizan IVA de 19%, salvo que el documento indique explícitamente una excepción.
9. El bruto de honorarios debe obtenerse del documento cuando sea posible.
10. Los valores faltantes pueden calcularse como fallback.
11. La cantidad de gastos es ilimitada.
12. Debe existir una exportación por caso.
13. Debe existir una exportación consolidada de múltiples casos.
14. Los datos deben mantener el formato necesario para que contabilidad pueda copiar y pegar las columnas directamente.
15. Cada archivo generado debe quedar versionado y asociado a los gastos que contiene.

---

## 18. Criterios de aceptación del MVP

El MVP se considera funcional cuando:

- [ ] ExpenseOps pregunta el centro de costo después de reconocer cada documento.
- [ ] El usuario puede seleccionar uno de los seis centros de costo de Porta.
- [ ] El centro de costo queda almacenado en el gasto.
- [ ] Un administrador puede corregir el centro de costo desde el backoffice.
- [ ] Solo los gastos aprobados se incluyen en la exportación.
- [ ] Cada gasto se escribe en la hoja correspondiente.
- [ ] Los gastos generales exportan fecha, documento, detalle y total.
- [ ] Las facturas exportan fecha, documento, detalle, neto, IVA y total.
- [ ] Las boletas de honorarios exportan fecha, documento, detalle, líquido, retención y bruto.
- [ ] El sistema calcula datos faltantes de factura cuando corresponde.
- [ ] El sistema valida la consistencia de los montos de honorarios.
- [ ] El archivo admite más filas que la plantilla original.
- [ ] Los totales y fórmulas se actualizan correctamente.
- [ ] Se puede descargar un Excel desde un caso cerrado.
- [ ] Se puede generar un Excel consolidado utilizando múltiples casos.
- [ ] El cierre financiero del caso no altera los gastos exportados.
- [ ] Cada exportación queda registrada y versionada.

---

## 19. Decisiones pendientes para validar con Porta

Antes de cerrar la implementación definitiva, conviene confirmar:

1. Si los seis conceptos deben llamarse formalmente “centros de costo” o “categorías contables”.
2. Si necesitan soportar facturas exentas o no afectas.
3. Qué regla de redondeo debe aplicarse al calcular neto e IVA.
4. Qué porcentaje de retención debe utilizarse como fallback para boletas de honorarios.
5. Si el Excel consolidado debe mantener exactamente las mismas columnas o puede incluir columnas de trazabilidad.
6. Si requieren conservar todas las versiones de los archivos generados.
7. Si necesitan una hoja adicional u oculta con trazabilidad.
8. Si los campos departamento y proyecto deben ser obligatorios o solo informativos.
9. Si el cierre del caso debe generar automáticamente el archivo o solamente dejarlo disponible para generación manual.

---

## 20. Definición resumida

> Al cerrar un caso, ExpenseOps debe generar una exportación contable independiente de la liquidación financiera. El archivo contiene exclusivamente los gastos aprobados, agrupados según el centro de costo seleccionado manualmente por el usuario. Porta tendrá seis centros de costo, cada uno asociado a una hoja del Excel. El OCR reconoce los datos del documento, pero siempre se solicita al usuario la clasificación contable. El sistema debe soportar una cantidad ilimitada de gastos, exportaciones por caso, exportaciones consolidadas y versionado de archivos.
