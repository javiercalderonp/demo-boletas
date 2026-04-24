import Link from "next/link";
import { Trash2, Mail, Clock, ShieldCheck, ArrowLeft } from "lucide-react";

import { BrandLogo } from "@/components/brand-logo";

export const metadata = {
  title: "Eliminación de datos — Expense Ops",
  description:
    "Instrucciones para solicitar la eliminación de tus datos personales de Expense Ops.",
};

const steps = [
  {
    number: "1",
    title: "Envía tu solicitud",
    description:
      'Escribe un correo a javier11calderon@gmail.com con el asunto "Solicitud de eliminación de datos". Incluye el número de teléfono asociado a tu cuenta de WhatsApp para que podamos identificar tus registros.',
  },
  {
    number: "2",
    title: "Verificación de identidad",
    description:
      "Te contactaremos para verificar tu identidad y confirmar la solicitud. Esto garantiza que solo tú puedas solicitar la eliminación de tus datos.",
  },
  {
    number: "3",
    title: "Procesamiento",
    description:
      "Una vez verificada tu identidad, procederemos a eliminar todos tus datos personales de nuestros sistemas en un plazo máximo de 30 días.",
  },
  {
    number: "4",
    title: "Confirmación",
    description:
      "Recibirás una confirmación por correo electrónico cuando tus datos hayan sido eliminados completamente.",
  },
];

const dataTypes = [
  "Nombre y datos de contacto",
  "Número de teléfono de WhatsApp",
  "Imágenes de boletas y comprobantes enviados",
  "Datos extraídos de documentos (montos, comercios, fechas)",
  "Historial de conversaciones con el bot",
  "Registros de gastos y rendiciones",
  "Información de casos y expedientes asociados",
];

export default function DataDeletionPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Navbar */}
      <nav className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex min-h-24 max-w-3xl items-center justify-between px-6 py-4">
          <BrandLogo size="sm" href="/" />
          <Link
            href="/landing"
            className="flex items-center gap-1.5 text-sm font-medium text-gray-600 hover:text-gray-900 transition"
          >
            <ArrowLeft className="h-4 w-4" />
            Volver al inicio
          </Link>
        </div>
      </nav>

      <main className="mx-auto max-w-3xl px-6 py-16">
        {/* Header */}
        <div className="mb-12">
          <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-red-100 text-red-600">
            <Trash2 className="h-6 w-6" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-gray-900">
            Eliminación de datos del usuario
          </h1>
          <p className="mt-3 text-lg text-gray-600">
            En Expense Ops respetamos tu privacidad. Puedes solicitar la eliminación completa
            de tus datos personales en cualquier momento siguiendo las instrucciones a continuación.
          </p>
        </div>

        {/* How to request */}
        <section className="mb-12">
          <h2 className="mb-6 text-xl font-semibold text-gray-900">
            Cómo solicitar la eliminación de tus datos
          </h2>
          <div className="space-y-4">
            {steps.map((step) => (
              <div
                key={step.number}
                className="flex gap-4 rounded-xl border border-gray-200 bg-white p-5"
              >
                <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-primary-100 text-sm font-bold text-primary-700">
                  {step.number}
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-gray-900">{step.title}</h3>
                  <p className="mt-1 text-sm leading-6 text-gray-600">{step.description}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Contact */}
        <section className="mb-12 rounded-xl border border-primary-200 bg-primary-50 p-6">
          <div className="flex items-start gap-3">
            <Mail className="mt-0.5 h-5 w-5 flex-shrink-0 text-primary-600" />
            <div>
              <h3 className="text-sm font-semibold text-primary-900">Contacto directo</h3>
              <p className="mt-1 text-sm text-primary-800">
                Envía tu solicitud a:{" "}
                <a
                  href="mailto:javier11calderon@gmail.com?subject=Solicitud%20de%20eliminación%20de%20datos"
                  className="font-semibold underline"
                >
                  javier11calderon@gmail.com
                </a>
              </p>
              <p className="mt-1 text-xs text-primary-700">
                Incluye tu número de teléfono de WhatsApp en el correo para agilizar el proceso.
              </p>
            </div>
          </div>
        </section>

        {/* What data */}
        <section className="mb-12">
          <h2 className="mb-4 text-xl font-semibold text-gray-900">
            Datos que se eliminan
          </h2>
          <p className="mb-4 text-sm text-gray-600">
            Al procesar tu solicitud, eliminaremos de forma permanente los siguientes datos
            asociados a tu cuenta:
          </p>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <ul className="space-y-3">
              {dataTypes.map((item) => (
                <li key={item} className="flex items-center gap-3 text-sm text-gray-700">
                  <span className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-red-100 text-red-600">
                    <Trash2 className="h-3 w-3" />
                  </span>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Timeline */}
        <section className="mb-12">
          <div className="flex items-start gap-4 rounded-xl border border-gray-200 bg-white p-6">
            <Clock className="mt-0.5 h-5 w-5 flex-shrink-0 text-gray-400" />
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Plazo de procesamiento</h3>
              <p className="mt-1 text-sm text-gray-600">
                Las solicitudes de eliminación se procesan dentro de un plazo máximo
                de <strong>30 días calendario</strong> a partir de la verificación de identidad.
                Recibirás una confirmación por correo electrónico una vez completado el proceso.
              </p>
            </div>
          </div>
        </section>

        {/* Commitment */}
        <section className="mb-12">
          <div className="flex items-start gap-4 rounded-xl border border-gray-200 bg-white p-6">
            <ShieldCheck className="mt-0.5 h-5 w-5 flex-shrink-0 text-green-600" />
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Nuestro compromiso</h3>
              <p className="mt-1 text-sm text-gray-600">
                Expense Ops cumple con las políticas de privacidad de Meta y WhatsApp Business Platform.
                Solo recopilamos los datos estrictamente necesarios para el funcionamiento del servicio
                de rendición de gastos, y nos comprometemos a eliminar toda la información cuando
                el usuario lo solicite.
              </p>
            </div>
          </div>
        </section>

        {/* Footer */}
        <footer className="border-t border-gray-200 pt-8 text-center">
          <p className="text-xs text-gray-400">
            Última actualización: abril 2026 &middot; Expense Ops &middot; Todos los derechos reservados.
          </p>
        </footer>
      </main>
    </div>
  );
}
