import Link from "next/link";
import { FileText, ArrowLeft } from "lucide-react";

import { BrandLogo } from "@/components/brand-logo";

export const metadata = {
  title: "Condiciones del Servicio — Expense Ops",
  description: "Condiciones del servicio de Expense Ops, plataforma de rendición de gastos por WhatsApp.",
};

export default function TermsPage() {
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
            <FileText className="h-6 w-6" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-gray-900">Condiciones del Servicio</h1>
          <p className="mt-2 text-sm text-gray-500">Última actualización: 14 de abril de 2026</p>
        </div>

        <div className="space-y-10">
          <Section title="1. Aceptación de las condiciones">
            <p>
              Al acceder o utilizar Expense Ops (&quot;el Servicio&quot;), ya sea a través de WhatsApp, el panel de
              administración (backoffice) o cualquier otro medio, aceptas estar sujeto a estas Condiciones del
              Servicio. Si no estás de acuerdo con alguna de estas condiciones, no debes utilizar el Servicio.
            </p>
            <p>
              Expense Ops es un servicio proporcionado para la gestión y rendición de gastos corporativos a través
              de WhatsApp Business Platform con procesamiento automatizado mediante inteligencia artificial.
            </p>
          </Section>

          <Section title="2. Descripción del servicio">
            <p>Expense Ops ofrece las siguientes funcionalidades:</p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>Recepción y procesamiento de comprobantes de gasto enviados por WhatsApp</li>
              <li>Extracción automática de datos de documentos mediante OCR e inteligencia artificial</li>
              <li>Asistente conversacional para guiar a los usuarios en el proceso de rendición</li>
              <li>Panel de administración para la gestión de personas, casos, gastos y conversaciones</li>
              <li>Validación automática de límites de gasto por empresa</li>
              <li>Dashboard operativo con métricas en tiempo real</li>
            </ul>
          </Section>

          <Section title="3. Tipos de usuarios">
            <h4 className="mt-2 text-sm font-semibold text-gray-900">3.1 Empleados (usuarios de WhatsApp)</h4>
            <p>
              Son las personas que envían comprobantes de gasto a través de WhatsApp. Acceden al servicio mediante
              su número de teléfono, previamente registrado por un administrador en el sistema.
            </p>
            <h4 className="mt-4 text-sm font-semibold text-gray-900">3.2 Administradores</h4>
            <p>
              Tienen acceso total al backoffice. Pueden crear y gestionar personas, casos, reglas y configuraciones
              del sistema.
            </p>
            <h4 className="mt-4 text-sm font-semibold text-gray-900">3.3 Operadores</h4>
            <p>
              Operan el día a día del sistema. Revisan gastos, corrigen datos y gestionan casos y conversaciones
              desde el backoffice.
            </p>
          </Section>

          <Section title="4. Uso aceptable">
            <p>Al utilizar el Servicio, te comprometes a:</p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>Proporcionar información veraz y precisa en tus rendiciones de gastos</li>
              <li>Enviar únicamente comprobantes legítimos y relacionados con gastos corporativos autorizados</li>
              <li>No utilizar el servicio para fines fraudulentos, ilegales o no autorizados</li>
              <li>No intentar acceder a datos de otros usuarios sin autorización</li>
              <li>No enviar contenido ofensivo, malicioso o que viole derechos de terceros</li>
              <li>No interferir con el funcionamiento del servicio o sus sistemas</li>
              <li>Mantener la confidencialidad de tus credenciales de acceso al backoffice</li>
            </ul>
          </Section>

          <Section title="5. Responsabilidad sobre los datos">
            <h4 className="mt-2 text-sm font-semibold text-gray-900">5.1 Precisión de datos</h4>
            <p>
              El procesamiento OCR e inteligencia artificial extrae datos de los documentos de forma automatizada.
              Si bien el sistema busca la mayor precisión posible, los datos extraídos pueden contener errores.
              Los operadores deben verificar y corregir los datos cuando sea necesario antes de aprobar un gasto.
            </p>
            <h4 className="mt-4 text-sm font-semibold text-gray-900">5.2 Documentos enviados</h4>
            <p>
              El usuario es responsable de la autenticidad y legitimidad de los documentos enviados.
              Expense Ops no se hace responsable de la veracidad de los comprobantes proporcionados por los usuarios.
            </p>
          </Section>

          <Section title="6. Propiedad intelectual">
            <p>
              El Servicio, incluyendo su software, diseño, funcionalidades y contenido, es propiedad de Expense Ops
              y está protegido por leyes de propiedad intelectual. No se concede al usuario ningún derecho de propiedad
              sobre el Servicio más allá del derecho de uso limitado descrito en estas condiciones.
            </p>
          </Section>

          <Section title="7. Disponibilidad del servicio">
            <p>
              Nos esforzamos por mantener el Servicio disponible de forma continua, sin embargo:
            </p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>No garantizamos disponibilidad ininterrumpida del servicio</li>
              <li>Podemos realizar mantenimientos programados que afecten temporalmente la disponibilidad</li>
              <li>La disponibilidad de WhatsApp depende de Meta Platforms y está fuera de nuestro control</li>
              <li>Nos reservamos el derecho de modificar, suspender o discontinuar el servicio con previo aviso</li>
            </ul>
          </Section>

          <Section title="8. Limitación de responsabilidad">
            <p>
              En la máxima medida permitida por la ley aplicable:
            </p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>
                El Servicio se proporciona &quot;tal cual&quot; y &quot;según disponibilidad&quot;, sin garantías
                de ningún tipo, ya sean expresas o implícitas.
              </li>
              <li>
                No seremos responsables de daños indirectos, incidentales, especiales o consecuentes derivados
                del uso o imposibilidad de uso del Servicio.
              </li>
              <li>
                No seremos responsables de errores en la extracción de datos por OCR o inteligencia artificial.
              </li>
              <li>
                No seremos responsables de pérdidas financieras derivadas de aprobaciones o rechazos de gastos
                basados en datos procesados por el sistema.
              </li>
            </ul>
          </Section>

          <Section title="9. Privacidad y datos personales">
            <p>
              El tratamiento de datos personales se rige por nuestra{" "}
              <Link href="/privacy/policy" className="font-medium text-primary-600 underline hover:text-primary-700">
                Política de Privacidad
              </Link>
              , que forma parte integral de estas condiciones. Al utilizar el Servicio, aceptas el tratamiento de
              tus datos conforme a dicha política.
            </p>
            <p>
              Puedes solicitar la eliminación de tus datos en cualquier momento siguiendo las instrucciones
              en nuestra{" "}
              <Link href="/privacy/data-deletion" className="font-medium text-primary-600 underline hover:text-primary-700">
                página de eliminación de datos
              </Link>.
            </p>
          </Section>

          <Section title="10. Integración con WhatsApp">
            <p>
              El Servicio utiliza la API de WhatsApp Business proporcionada por Meta Platforms, Inc. Al
              interactuar con el Servicio a través de WhatsApp:
            </p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>Aceptas cumplir con los Términos de Servicio de WhatsApp</li>
              <li>Reconoces que Meta puede procesar datos de acuerdo con sus propias políticas</li>
              <li>Entiendes que la disponibilidad del canal de WhatsApp depende de Meta</li>
            </ul>
          </Section>

          <Section title="11. Terminación">
            <p>
              Podemos suspender o terminar tu acceso al Servicio si:
            </p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>Incumples estas Condiciones del Servicio</li>
              <li>Utilizas el Servicio de forma fraudulenta o abusiva</li>
              <li>Tu empresa finaliza la relación contractual con Expense Ops</li>
              <li>Es necesario por razones legales o de seguridad</li>
            </ul>
            <p>
              En caso de terminación, mantendremos tus datos según lo establecido en nuestra Política de
              Privacidad, salvo que solicites su eliminación.
            </p>
          </Section>

          <Section title="12. Modificaciones">
            <p>
              Nos reservamos el derecho de modificar estas condiciones en cualquier momento. Las modificaciones
              entrarán en vigor a partir de su publicación en esta página. El uso continuado del Servicio tras
              la publicación de modificaciones constituye la aceptación de las nuevas condiciones.
            </p>
          </Section>

          <Section title="13. Legislación aplicable">
            <p>
              Estas condiciones se rigen por las leyes de la República de Chile. Cualquier controversia derivada
              de estas condiciones o del uso del Servicio será sometida a la jurisdicción de los tribunales
              competentes de Santiago de Chile.
            </p>
          </Section>

          <Section title="14. Contacto">
            <p>
              Para consultas sobre estas condiciones, puedes contactarnos en:
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
            <Link href="/privacy/policy" className="hover:text-gray-700 transition">Política de privacidad</Link>
            <Link href="/privacy/data-deletion" className="hover:text-gray-700 transition">Eliminación de datos</Link>
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
