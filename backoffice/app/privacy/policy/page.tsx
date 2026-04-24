import Link from "next/link";
import { ShieldCheck, ArrowLeft } from "lucide-react";

import { BrandLogo } from "@/components/brand-logo";

export const metadata = {
  title: "Política de Privacidad — Expense Ops",
  description: "Política de privacidad de Expense Ops, plataforma de rendición de gastos por WhatsApp.",
};

export default function PrivacyPolicyPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex min-h-24 max-w-3xl items-center justify-between px-6 py-4">
          <BrandLogo size="sm" href="/" />
          <Link href="/landing" className="flex items-center gap-1.5 text-sm font-medium text-gray-600 hover:text-gray-900 transition">
            <ArrowLeft className="h-4 w-4" />
            Volver al inicio
          </Link>
        </div>
      </nav>

      <main className="mx-auto max-w-3xl px-6 py-16">
        <div className="mb-12">
          <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-primary-100 text-primary-600">
            <ShieldCheck className="h-6 w-6" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-gray-900">Política de Privacidad</h1>
          <p className="mt-2 text-sm text-gray-500">Última actualización: 14 de abril de 2026</p>
        </div>

        <div className="space-y-10">
          <Section title="1. Introducción">
            <p>
              Expense Ops (&quot;nosotros&quot;, &quot;nuestro&quot; o &quot;la plataforma&quot;) es un servicio de gestión
              y rendición de gastos corporativos que opera a través de la integración con WhatsApp Business
              Platform. Esta política de privacidad describe cómo recopilamos, usamos, almacenamos y protegemos
              la información personal de los usuarios de nuestro servicio.
            </p>
            <p>
              Al utilizar Expense Ops, ya sea a través de WhatsApp o del panel de administración (backoffice),
              aceptas las prácticas descritas en esta política.
            </p>
          </Section>

          <Section title="2. Información que recopilamos">
            <p>Recopilamos los siguientes tipos de información:</p>
            <h4 className="mt-4 text-sm font-semibold text-gray-900">2.1 Información proporcionada por el usuario</h4>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>Nombre completo</li>
              <li>Número de teléfono de WhatsApp</li>
              <li>RUT o documento de identidad</li>
              <li>Correo electrónico</li>
              <li>Empresa u organización asociada</li>
            </ul>
            <h4 className="mt-4 text-sm font-semibold text-gray-900">2.2 Información generada por el uso del servicio</h4>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>Imágenes de boletas y comprobantes de gasto enviadas por WhatsApp</li>
              <li>Datos extraídos mediante OCR (comercio, monto, fecha, moneda, categoría, país)</li>
              <li>Historial de conversaciones con el asistente automatizado</li>
              <li>Registros de gastos, casos y rendiciones</li>
              <li>Metadatos de uso (fechas de actividad, estados de conversación)</li>
            </ul>
            <h4 className="mt-4 text-sm font-semibold text-gray-900">2.3 Información de operadores del backoffice</h4>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>Nombre y correo electrónico de acceso</li>
              <li>Rol asignado (administrador u operador)</li>
              <li>Registros de acciones realizadas en el sistema</li>
            </ul>
          </Section>

          <Section title="3. Cómo usamos la información">
            <p>Utilizamos la información recopilada para:</p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>Procesar y registrar rendiciones de gastos enviadas por WhatsApp</li>
              <li>Extraer datos de documentos mediante inteligencia artificial y OCR</li>
              <li>Gestionar expedientes (casos) de rendición por empresa y empleado</li>
              <li>Facilitar la revisión, aprobación o rechazo de gastos por parte de operadores</li>
              <li>Enviar confirmaciones y solicitar información adicional a través de WhatsApp</li>
              <li>Generar métricas y alertas operativas en el panel de administración</li>
              <li>Verificar límites de gasto configurados por empresa</li>
            </ul>
          </Section>

          <Section title="4. Base legal para el procesamiento">
            <p>Procesamos datos personales con las siguientes bases legales:</p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li><strong>Ejecución contractual:</strong> el procesamiento es necesario para prestar el servicio de rendición de gastos contratado por la empresa del usuario.</li>
              <li><strong>Consentimiento:</strong> el usuario consiente el procesamiento de sus datos al enviar voluntariamente documentos y datos a través de WhatsApp.</li>
              <li><strong>Interés legítimo:</strong> el procesamiento es necesario para la operación interna, seguridad y mejora del servicio.</li>
            </ul>
          </Section>

          <Section title="5. Almacenamiento y seguridad">
            <p>
              Los datos se almacenan en sistemas seguros con acceso restringido. Implementamos las siguientes
              medidas de seguridad:
            </p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>Comunicación cifrada mediante HTTPS en todas las conexiones</li>
              <li>Cifrado de extremo a extremo en la comunicación por WhatsApp (proporcionado por Meta)</li>
              <li>Autenticación basada en tokens JWT para el acceso al backoffice</li>
              <li>Control de acceso basado en roles (administrador y operador)</li>
              <li>Acceso restringido a datos según el rol del usuario</li>
            </ul>
          </Section>

          <Section title="6. Compartición de datos con terceros">
            <p>Podemos compartir información con los siguientes terceros, exclusivamente para la prestación del servicio:</p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li><strong>Meta / WhatsApp Business Platform:</strong> para el envío y recepción de mensajes a través de WhatsApp.</li>
              <li><strong>Servicios de inteligencia artificial:</strong> para el procesamiento OCR y extracción de datos de documentos.</li>
              <li><strong>Google Sheets:</strong> como sistema de almacenamiento de datos operativos.</li>
              <li><strong>Proveedores de hosting:</strong> para el alojamiento de la infraestructura del servicio.</li>
            </ul>
            <p className="mt-3">
              No vendemos, alquilamos ni compartimos datos personales con terceros para fines de marketing o publicidad.
            </p>
          </Section>

          <Section title="7. Retención de datos">
            <p>
              Retenemos los datos personales durante el tiempo necesario para cumplir con los fines descritos en
              esta política, o según lo requieran obligaciones legales o contractuales. Los criterios para determinar
              el período de retención incluyen:
            </p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>Duración de la relación comercial con la empresa del usuario</li>
              <li>Requisitos legales de conservación de documentos contables</li>
              <li>Necesidades operativas del servicio</li>
            </ul>
          </Section>

          <Section title="8. Derechos del usuario">
            <p>Los usuarios tienen derecho a:</p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li><strong>Acceso:</strong> solicitar una copia de los datos personales que tenemos sobre ellos.</li>
              <li><strong>Rectificación:</strong> solicitar la corrección de datos inexactos o incompletos.</li>
              <li><strong>Eliminación:</strong> solicitar la eliminación de sus datos personales. Consulta nuestra{" "}
                <Link href="/privacy/data-deletion" className="font-medium text-primary-600 underline hover:text-primary-700">
                  página de eliminación de datos
                </Link> para más detalles.
              </li>
              <li><strong>Oposición:</strong> oponerse al procesamiento de sus datos en determinadas circunstancias.</li>
              <li><strong>Portabilidad:</strong> solicitar la transferencia de sus datos a otro servicio.</li>
            </ul>
            <p className="mt-3">
              Para ejercer cualquiera de estos derechos, contacta a{" "}
              <a href="mailto:javier11calderon@gmail.com" className="font-medium text-primary-600 underline hover:text-primary-700">
                javier11calderon@gmail.com
              </a>.
            </p>
          </Section>

          <Section title="9. Uso de WhatsApp Business Platform">
            <p>
              Nuestro servicio utiliza la API de WhatsApp Business proporcionada por Meta Platforms, Inc.
              Al interactuar con nuestro servicio a través de WhatsApp:
            </p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>Los mensajes se procesan de acuerdo con las políticas de Meta y WhatsApp.</li>
              <li>Meta puede tener acceso a metadatos de la comunicación según sus propias políticas de privacidad.</li>
              <li>Recomendamos consultar la{" "}
                <span className="font-medium text-gray-900">Política de Privacidad de WhatsApp</span>{" "}
                para entender cómo Meta procesa los datos de mensajería.
              </li>
            </ul>
          </Section>

          <Section title="10. Cambios a esta política">
            <p>
              Podemos actualizar esta política de privacidad periódicamente. En caso de cambios significativos,
              notificaremos a los usuarios a través de los canales disponibles. La fecha de la última
              actualización se indica al inicio de este documento.
            </p>
          </Section>

          <Section title="11. Contacto">
            <p>
              Si tienes preguntas sobre esta política de privacidad o sobre el tratamiento de tus datos
              personales, puedes contactarnos en:
            </p>
            <div className="mt-4 rounded-xl border border-gray-200 bg-white p-5">
              <p className="text-sm font-semibold text-gray-900">Expense Ops</p>
              <p className="mt-1 text-sm text-gray-600">
                Correo electrónico:{" "}
                <a href="mailto:javier11calderon@gmail.com" className="font-medium text-primary-600 underline">
                  javier11calderon@gmail.com
                </a>
              </p>
            </div>
          </Section>
        </div>

        <footer className="mt-16 border-t border-gray-200 pt-8 text-center">
          <div className="flex justify-center gap-6 text-sm text-gray-500">
            <Link href="/privacy/data-deletion" className="hover:text-gray-700 transition">Eliminación de datos</Link>
            <Link href="/privacy/terms" className="hover:text-gray-700 transition">Condiciones del servicio</Link>
          </div>
          <p className="mt-4 text-xs text-gray-400">&copy; 2026 Expense Ops. Todos los derechos reservados.</p>
        </footer>
      </main>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-4 text-lg font-semibold text-gray-900">{title}</h2>
      <div className="space-y-3 text-sm leading-7 text-gray-600">{children}</div>
    </section>
  );
}
