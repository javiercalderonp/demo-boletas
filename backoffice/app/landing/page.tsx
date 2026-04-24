import Link from "next/link";
import {
  MessageSquare,
  Camera,
  Brain,
  ShieldCheck,
  BarChart3,
  Clock,
  Users,
  FileCheck,
  ArrowRight,
  CheckCircle2,
  Zap,
  Globe,
  Lock,
} from "lucide-react";

import { BrandLogo } from "@/components/brand-logo";

export const metadata = {
  title: "Expense Ops — Gestión de Viáticos por WhatsApp",
  description:
    "Plataforma automatizada de rendición de gastos y viáticos a través de WhatsApp con OCR inteligente y backoffice integrado.",
};

const features = [
  {
    icon: MessageSquare,
    title: "Rendición por WhatsApp",
    description:
      "Los empleados envían fotos de sus boletas directamente por WhatsApp. Sin apps adicionales, sin capacitación.",
    color: "bg-green-100 text-green-700",
  },
  {
    icon: Camera,
    title: "OCR Inteligente",
    description:
      "Extracción automática de comercio, monto, fecha, moneda y categoría usando inteligencia artificial avanzada.",
    color: "bg-blue-100 text-blue-700",
  },
  {
    icon: Brain,
    title: "Asistente Conversacional",
    description:
      "Bot inteligente que guía al empleado paso a paso, solicita información faltante y confirma cada gasto.",
    color: "bg-purple-100 text-purple-700",
  },
  {
    icon: ShieldCheck,
    title: "Validación Automática",
    description:
      "Control de límites por boleta y por caso. Alertas cuando se superan montos máximos configurados.",
    color: "bg-amber-100 text-amber-700",
  },
  {
    icon: BarChart3,
    title: "Backoffice Operativo",
    description:
      "Panel de administración completo para gestionar personas, casos, gastos y conversaciones en tiempo real.",
    color: "bg-indigo-100 text-indigo-700",
  },
  {
    icon: Clock,
    title: "Operación en Tiempo Real",
    description:
      "Dashboard con métricas, alertas y estado del sistema actualizado automáticamente desde Google Sheets.",
    color: "bg-rose-100 text-rose-700",
  },
];

const steps = [
  {
    number: "01",
    title: "El administrador crea un caso",
    description:
      "Se asigna un expediente al empleado con límites de gasto configurados por empresa.",
  },
  {
    number: "02",
    title: "El empleado envía boletas por WhatsApp",
    description:
      "Simplemente toma una foto del comprobante y la envía al número de la empresa.",
  },
  {
    number: "03",
    title: "IA procesa el documento",
    description:
      "El sistema extrae todos los datos relevantes, verifica límites y solicita información faltante.",
  },
  {
    number: "04",
    title: "El operador revisa y aprueba",
    description:
      "Desde el backoffice, el equipo financiero revisa, corrige y aprueba cada rendición.",
  },
];

const stats = [
  { value: "90%", label: "Reducción en tiempo de rendición" },
  { value: "0", label: "Apps adicionales necesarias" },
  { value: "24/7", label: "Disponibilidad del sistema" },
  { value: "<30s", label: "Procesamiento por documento" },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-white">
      {/* Navbar */}
      <nav className="sticky top-0 z-50 border-b border-gray-100 bg-white/80 backdrop-blur-lg">
        <div className="mx-auto flex min-h-24 max-w-6xl items-center justify-between px-6 py-4">
          <BrandLogo size="sm" href="/" />
          <div className="hidden items-center gap-8 sm:flex">
            <a href="#features" className="text-sm font-medium text-gray-600 hover:text-gray-900 transition">
              Funcionalidades
            </a>
            <a href="#how-it-works" className="text-sm font-medium text-gray-600 hover:text-gray-900 transition">
              Cómo funciona
            </a>
            <a href="#security" className="text-sm font-medium text-gray-600 hover:text-gray-900 transition">
              Seguridad
            </a>
          </div>
          <Link
            href="/login"
            className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700"
          >
            Ingresar
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-primary-50 via-white to-purple-50" />
        <div className="absolute inset-0" style={{ backgroundImage: "radial-gradient(circle at 1px 1px, rgba(99,102,241,0.07) 1px, transparent 0)", backgroundSize: "40px 40px" }} />
        <div className="relative mx-auto max-w-6xl px-6 pb-24 pt-20 sm:pb-32 sm:pt-28">
          <div className="mx-auto max-w-3xl text-center">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full bg-primary-50 px-4 py-1.5 text-sm font-medium text-primary-700 ring-1 ring-inset ring-primary-200">
              <Zap className="h-4 w-4" />
              Plataforma de rendición inteligente
            </div>
            <h1 className="text-4xl font-bold tracking-tight text-gray-900 sm:text-5xl lg:text-6xl">
              Rendición de gastos
              <span className="block text-primary-600">por WhatsApp</span>
            </h1>
            <p className="mt-6 text-lg leading-8 text-gray-600 sm:text-xl">
              Automatiza la rendición de viáticos y gastos corporativos. Tus empleados envían boletas por WhatsApp
              y nuestro sistema las procesa con inteligencia artificial en segundos.
            </p>
            <div className="mt-10 flex flex-col items-center gap-4 sm:flex-row sm:justify-center">
              <Link
                href="/login"
                className="flex items-center gap-2 rounded-xl bg-primary-600 px-6 py-3.5 text-sm font-semibold text-white shadow-lg shadow-primary-600/25 transition hover:bg-primary-700 hover:shadow-primary-600/30"
              >
                Acceder al backoffice
                <ArrowRight className="h-4 w-4" />
              </Link>
              <a
                href="#how-it-works"
                className="flex items-center gap-2 rounded-xl border border-gray-300 bg-white px-6 py-3.5 text-sm font-semibold text-gray-700 transition hover:bg-gray-50"
              >
                Ver cómo funciona
              </a>
            </div>
          </div>

          {/* Stats bar */}
          <div className="mx-auto mt-20 grid max-w-4xl grid-cols-2 gap-4 sm:grid-cols-4">
            {stats.map((stat) => (
              <div key={stat.label} className="rounded-2xl bg-white/80 p-6 text-center shadow-sm ring-1 ring-gray-200/60 backdrop-blur">
                <p className="text-3xl font-bold text-primary-600">{stat.value}</p>
                <p className="mt-1 text-sm text-gray-500">{stat.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="bg-gray-50 py-24">
        <div className="mx-auto max-w-6xl px-6">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-sm font-semibold uppercase tracking-wider text-primary-600">Funcionalidades</p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl">
              Todo lo que necesitas para gestionar viáticos
            </h2>
            <p className="mt-4 text-lg text-gray-600">
              Una plataforma completa que conecta WhatsApp, OCR e inteligencia artificial para simplificar la rendición de gastos.
            </p>
          </div>
          <div className="mt-16 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {features.map((feature) => (
              <div
                key={feature.title}
                className="group rounded-2xl border border-gray-200 bg-white p-6 shadow-sm transition hover:shadow-md hover:border-gray-300"
              >
                <div className={`mb-4 inline-flex h-12 w-12 items-center justify-center rounded-xl ${feature.color}`}>
                  <feature.icon className="h-6 w-6" />
                </div>
                <h3 className="text-lg font-semibold text-gray-900">{feature.title}</h3>
                <p className="mt-2 text-sm leading-6 text-gray-600">{feature.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how-it-works" className="py-24">
        <div className="mx-auto max-w-6xl px-6">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-sm font-semibold uppercase tracking-wider text-primary-600">Proceso</p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl">
              Cómo funciona
            </h2>
            <p className="mt-4 text-lg text-gray-600">
              Un flujo simple y automatizado desde la foto de la boleta hasta la aprobación del gasto.
            </p>
          </div>
          <div className="mt-16 grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-4">
            {steps.map((step, index) => (
              <div key={step.number} className="relative">
                {index < steps.length - 1 && (
                  <div className="absolute right-0 top-8 hidden h-px w-full translate-x-1/2 bg-gradient-to-r from-primary-300 to-transparent lg:block" />
                )}
                <div className="relative rounded-2xl border border-gray-200 bg-white p-6">
                  <span className="text-4xl font-bold text-primary-100">{step.number}</span>
                  <h3 className="mt-4 text-base font-semibold text-gray-900">{step.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-gray-600">{step.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* WhatsApp integration section */}
      <section className="bg-gradient-to-br from-green-50 to-emerald-50 py-24">
        <div className="mx-auto max-w-6xl px-6">
          <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2">
            <div>
              <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-green-100 px-4 py-1.5 text-sm font-medium text-green-700">
                <MessageSquare className="h-4 w-4" />
                Integración WhatsApp Business
              </div>
              <h2 className="text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl">
                La herramienta que tus empleados ya usan
              </h2>
              <p className="mt-4 text-lg text-gray-600">
                No requiere instalación de aplicaciones, capacitación compleja ni cambios de hábito.
                WhatsApp es la plataforma de mensajería más usada en Latinoamérica y el canal perfecto para rendiciones de gastos.
              </p>
              <ul className="mt-8 space-y-4">
                {[
                  "Envío de boletas con solo una foto",
                  "Confirmación y corrección conversacional",
                  "Notificaciones de estado en tiempo real",
                  "Soporte multiidioma y multimoneda",
                  "Cifrado de extremo a extremo por WhatsApp",
                ].map((item) => (
                  <li key={item} className="flex items-start gap-3">
                    <CheckCircle2 className="mt-0.5 h-5 w-5 flex-shrink-0 text-green-600" />
                    <span className="text-sm text-gray-700">{item}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="flex justify-center">
              <div className="w-80 rounded-3xl bg-white p-4 shadow-2xl shadow-green-900/10 ring-1 ring-gray-200">
                {/* Simulated chat */}
                <div className="mb-4 flex items-center gap-3 border-b border-gray-100 pb-3">
                  <BrandLogo size="sm" className="h-10" />
                  <div>
                    <p className="text-sm font-semibold text-gray-900">Expense Ops</p>
                    <p className="text-xs text-green-600">en línea</p>
                  </div>
                </div>
                <div className="space-y-3">
                  <div className="ml-auto w-fit max-w-[75%] rounded-2xl rounded-tr-md bg-green-100 px-4 py-2.5">
                    <p className="text-sm text-gray-800">Hola, necesito rendir una boleta</p>
                  </div>
                  <div className="w-fit max-w-[75%] rounded-2xl rounded-tl-md bg-gray-100 px-4 py-2.5">
                    <p className="text-sm text-gray-800">Hola Juan. Envíame la foto de tu boleta y la proceso al instante.</p>
                  </div>
                  <div className="ml-auto w-fit rounded-2xl rounded-tr-md bg-green-100 px-4 py-2.5">
                    <div className="flex items-center gap-2 text-sm text-gray-600">
                      <Camera className="h-4 w-4" />
                      boleta_almuerzo.jpg
                    </div>
                  </div>
                  <div className="w-fit max-w-[75%] rounded-2xl rounded-tl-md bg-gray-100 px-4 py-2.5">
                    <p className="text-sm text-gray-800">
                      Registrado: Restaurante El Parrón, $12.500 CLP, categoría Alimentación. ¿Es correcto?
                    </p>
                  </div>
                  <div className="ml-auto w-fit rounded-2xl rounded-tr-md bg-green-100 px-4 py-2.5">
                    <p className="text-sm text-gray-800">Sí, correcto</p>
                  </div>
                  <div className="w-fit max-w-[75%] rounded-2xl rounded-tl-md bg-gray-100 px-4 py-2.5">
                    <p className="text-sm text-gray-800">Gasto registrado exitosamente. Puedes enviar otra boleta cuando quieras.</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Security */}
      <section id="security" className="py-24">
        <div className="mx-auto max-w-6xl px-6">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-sm font-semibold uppercase tracking-wider text-primary-600">Seguridad y cumplimiento</p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl">
              Datos protegidos en cada paso
            </h2>
          </div>
          <div className="mt-12 grid grid-cols-1 gap-6 sm:grid-cols-3">
            {[
              {
                icon: Lock,
                title: "Autenticación segura",
                description: "Acceso al backoffice protegido con autenticación JWT y control de roles (admin/operador).",
              },
              {
                icon: ShieldCheck,
                title: "Cifrado de datos",
                description: "Comunicación cifrada end-to-end a través de WhatsApp y HTTPS en todas las conexiones del sistema.",
              },
              {
                icon: Globe,
                title: "Cumplimiento",
                description: "Diseñado para cumplir con las políticas de uso de la API de WhatsApp Business y protección de datos personales.",
              },
            ].map((item) => (
              <div key={item.title} className="rounded-2xl border border-gray-200 bg-white p-6 text-center">
                <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-primary-50 text-primary-600">
                  <item.icon className="h-6 w-6" />
                </div>
                <h3 className="text-base font-semibold text-gray-900">{item.title}</h3>
                <p className="mt-2 text-sm text-gray-600">{item.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Use cases */}
      <section className="bg-gray-50 py-24">
        <div className="mx-auto max-w-6xl px-6">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-sm font-semibold uppercase tracking-wider text-primary-600">Casos de uso</p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl">
              Ideal para equipos que operan en terreno
            </h2>
          </div>
          <div className="mt-12 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {[
              {
                icon: Users,
                title: "Viáticos corporativos",
                description: "Gestión completa de gastos de viaje, alimentación y transporte para equipos en movimiento.",
              },
              {
                icon: FileCheck,
                title: "Rendiciones de campo",
                description: "Empleados en terreno rinden gastos al instante sin esperar a volver a la oficina.",
              },
              {
                icon: BarChart3,
                title: "Control financiero",
                description: "Visibilidad total de gastos por persona, empresa y caso con límites configurables.",
              },
            ].map((item) => (
              <div key={item.title} className="rounded-2xl border border-gray-200 bg-white p-6">
                <div className="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-lg bg-primary-50 text-primary-600">
                  <item.icon className="h-5 w-5" />
                </div>
                <h3 className="text-base font-semibold text-gray-900">{item.title}</h3>
                <p className="mt-2 text-sm leading-6 text-gray-600">{item.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24">
        <div className="mx-auto max-w-6xl px-6">
          <div className="rounded-3xl bg-gradient-to-br from-primary-600 to-primary-800 px-8 py-16 text-center sm:px-16">
            <h2 className="text-3xl font-bold text-white sm:text-4xl">
              Simplifica la rendición de gastos de tu empresa
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-lg text-primary-100">
              Comienza a operar hoy. Sin instalaciones, sin fricciones, usando el canal que tus empleados ya conocen.
            </p>
            <div className="mt-10">
              <Link
                href="/login"
                className="inline-flex items-center gap-2 rounded-xl bg-white px-8 py-4 text-sm font-semibold text-primary-700 shadow-lg transition hover:bg-primary-50"
              >
                Acceder al sistema
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-200 bg-white py-12">
        <div className="mx-auto max-w-6xl px-6">
          <div className="flex flex-col items-center justify-between gap-6 sm:flex-row">
            <BrandLogo size="sm" href="/" />
            <div className="flex items-center gap-6 text-sm text-gray-500">
              <a href="#features" className="hover:text-gray-700 transition">Funcionalidades</a>
              <a href="#how-it-works" className="hover:text-gray-700 transition">Cómo funciona</a>
              <a href="#security" className="hover:text-gray-700 transition">Seguridad</a>
            </div>
            <p className="text-sm text-gray-400">
              &copy; {new Date().getFullYear()} Expense Ops. Todos los derechos reservados.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
