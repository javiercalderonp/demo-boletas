# Observaciones para el equipo de ExpenseOps

Documento interno. No forma parte de la guía que se entrega al cliente.

## Alcance revisado

Se revisaron las rutas y componentes del backoffice, los tipos compartidos, permisos por empresa, validaciones de formularios, acciones expuestas, servicios operativos, flujo de WhatsApp, estados y pruebas relacionadas. La guía se limitó al rol `company_admin`.

## Funciones excluidas de la guía

- **Usuarios** y **Auditoría**: el menú las oculta al administrador de empresa y sus operaciones requieren privilegios globales.
- Acciones técnicas o globales de mantenimiento.
- Funciones propuestas en `docs/workflows/expense-submission.md` que aún no aparecen como flujo completo en la interfaz.
- Traslado de un gasto entre casos y reapertura de rendiciones: no hay controles visibles.
- “Observar” y “Revisión manual” como acciones: existen en el contrato y servicio, pero no hay botones para ejecutarlas en las pantallas de gastos.

## Inconsistencias y puntos poco claros

1. **“Casos” versus “Rendiciones”.** El menú dice “Casos”, la página se titula “Rendiciones” y varias acciones mezclan ambos términos. Conviene elegir “Rendiciones” para toda la experiencia del cliente.
2. **Estados incompletos en el Dashboard.** Los tipos incluyen `pending_company_review`, pero el gráfico solo etiqueta abierta, esperando confirmación, aprobada y cerrada. Un valor no previsto se mostraría sin traducir.
3. **Estados técnicos en Conversaciones.** El filtro y las insignias muestran valores como `WAIT_RECEIPT`, `PROCESSING` y `NEEDS_INFO`, impropios para un usuario no técnico.
4. **Rol visible sin traducción.** El pie del menú muestra `company_admin` en lugar de “Administrador de empresa”.
5. **Buscador superior sin función.** El campo global “Buscar...” en `Shell` no tiene lógica asociada. Puede inducir a pensar que busca en toda la plataforma.
6. **“Observar” sin interfaz.** La operación existe, exige motivo, cambia estados y notifica por WhatsApp, pero el administrador solo ve Aprobar y Rechazar.
7. **Revisión manual sin interfaz.** Está presente en estados, filtros y servicio, pero no existe una acción visible para asignarla.
8. **Estado y resultado del gasto mezclados.** La UI usa `status` y `review_status`; en algunos lugares se normalizan y en otros se muestra directamente el valor. Esto puede producir etiquetas distintas para el mismo gasto.
9. **Puntaje sin explicación operativa.** El detalle muestra puntaje, desglose y banderas, pero no indica umbrales ni que la decisión final sigue siendo humana.
10. **Edición de persona y teléfono.** La vista de detalle no permite editar el teléfono porque este se usa como clave de la ruta, mientras el listado abre un formulario que sí carga el teléfono. Debe confirmarse el comportamiento esperado al cambiarlo y su efecto en casos, gastos y conversación.
11. **Eliminación riesgosa.** Personas y casos pueden eliminarse desde la interfaz. En Personas se ofrece eliminar también casos; conviene restringir o reforzar la confirmación en ambientes de clientes.
12. **Edición de caso desigual.** El formulario del listado permite editar más campos que la edición del detalle, que se limita a empresa, método de cierre y centros de costo.
13. **País no forma parte del alta de caso.** Aunque era un posible campo de la estructura solicitada, el formulario actual no lo incluye.
14. **Cierre administrativo forzado.** El detalle permite forzar un cierre con liquidación pendiente después de una confirmación. Es una excepción de alto impacto y necesita una política de uso y trazabilidad claramente aprobada.
15. **Reapertura no visible.** El servicio admite la acción heredada `reopen`, pero ninguna pantalla ofrece el control. La FAQ indica correctamente que se debe escalar.
16. **Traslado de gastos no disponible.** No existe control para reasignar un gasto a otro caso, aunque es una incidencia operativa esperable.
17. **Aprobación masiva.** Permite aprobar varios documentos con una confirmación, sin abrirlos obligatoriamente. Es eficiente, pero aumenta el riesgo de aprobación sin revisar el original.
18. **Rechazo masivo con un mismo motivo.** El motivo se aplica a todos los seleccionados; debería advertirse si los documentos tienen problemas distintos.
19. **Mensajes silenciosamente fallidos.** Algunas notificaciones de cierre se envían mediante una función tolerante a errores; el administrador puede no distinguir un cambio de estado exitoso de una notificación fallida.
20. **Creación con WhatsApp fallido.** El alta del caso sí informa el fallo del mensaje inicial, pero no ofrece reintento directo.
21. **Contraseña olvidada.** Solo existe activación inicial mediante “No tengo clave aún”. No hay recuperación o restablecimiento autónomo para cuentas ya activadas.
22. **PDF consolidado.** El botón “Descargar PDF” realiza primero una generación. Si falla por configuración externa o datos faltantes, el usuario solo ve el error; conviene explicar requisitos en pantalla.
23. **DocuSign versus Cierre Simple.** Ambos métodos se eligen al crear el caso, pero la disponibilidad efectiva de DocuSign depende de la configuración del ambiente. Confirmar cuál se ofrecerá a cada cliente.
24. **Cierre contable en Dashboard.** Es una función relevante y compleja ubicada en la portada, no en una sección “Reportes”. Puede dificultar su descubrimiento y recargar la operación diaria.
25. **Exportación CSV y filtros.** Los botones de exportación llaman a rutas sin transportar los filtros aplicados en la interfaz; el archivo puede contener más registros que los visibles. El texto de la guía evita afirmar que el CSV respeta los filtros.
26. **Eliminación de cierres contables.** El administrador de empresa puede borrar exportaciones generadas. Confirmar si esto debe estar permitido por política contable.
27. **Datos bancarios sensibles.** Se muestran y copian desde el detalle de la rendición. Conviene definir permisos, enmascaramiento y registro de acceso.
28. **Empresa visible como selector.** Para `company_admin`, los servicios fuerzan la empresa autorizada, pero algunos formularios siguen mostrando controles o identificadores de empresa. Sería más claro mostrarla como texto no editable.

## Confirmaciones recomendadas antes de entregar la guía

- Definir si el nombre comercial final será ExpenseOps y actualizar el logotipo/textos si corresponde.
- Confirmar el método de cierre habilitado para la empresa cliente.
- Definir quién puede usar el cierre administrativo forzado y eliminar registros.
- Confirmar el procedimiento oficial para cambio de teléfono, traslado de gastos, reapertura y recuperación de contraseña.
- Decidir si se implementará **Observar** antes de capacitar al cliente.
- Validar los textos exactos que recibe la persona por WhatsApp en cada ambiente.
- Completar correo, teléfono y horario de soporte.

## Recomendaciones de experiencia

- Unificar “Caso” y “Rendición” y traducir todos los estados.
- Implementar o retirar el buscador superior.
- Incorporar una acción visible **Observar y solicitar antecedentes**.
- Separar con claridad “estado de revisión”, “decisión del gasto”, “estado de rendición” y “liquidación”.
- Añadir reintento y estado de entrega para notificaciones de WhatsApp.
- Restringir acciones destructivas y de cierre forzado mediante permisos específicos.
- Hacer que las exportaciones indiquen expresamente el alcance y los filtros incluidos.
- Agregar ayuda contextual al puntaje de revisión y a la liquidación final.

## Capturas

La guía incluye diez marcadores de captura sugerida. No se incorporaron imágenes reales porque el repositorio local no dispone de un ambiente autónomo con datos anonimizados y credenciales de administrador de empresa; el frontend configurado depende del servicio externo. Antes de publicar, realizar las capturas en un ambiente de demostración exclusivo de una sola empresa y reemplazar teléfonos, RUT, correos, cuentas bancarias e identificadores por datos ficticios.
