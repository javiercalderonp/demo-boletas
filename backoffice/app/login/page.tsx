"use client";

import { FormEvent, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { BrandLogo } from "@/components/brand-logo";
import { apiRequest, getStoredLoginEmail } from "@/lib/api";

export default function LoginPage() {
  const { login, setupPassword } = useAuth();
  const [mode, setMode] = useState<"login" | "requestSetup" | "setup">("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirmation, setPasswordConfirmation] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setEmail(getStoredLoginEmail());
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      if (mode === "login") {
        await login(email, password);
      } else if (mode === "requestSetup") {
        const data = await apiRequest<{ email: string; name?: string; can_setup_password: boolean }>(
          "/auth/setup-password/request",
          {
            method: "POST",
            body: { email },
          },
        );
        setEmail(data.email);
        setName(data.name || "");
        setPassword("");
        setPasswordConfirmation("");
        setMode("setup");
      } else {
        if (password !== passwordConfirmation) {
          throw new Error("Las claves no coinciden.");
        }
        await setupPassword(email, name, password);
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "No se pudo completar la solicitud.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <BrandLogo size="lg" href="/" priority className="mx-auto mb-4" />
          <p className="mt-2 text-sm text-gray-500">
            {mode === "login"
              ? "Ingresa con tu cuenta para administrar operaciones."
              : mode === "requestSetup"
                ? "Usa el email que registró un administrador."
                : "Elige tu clave para activar tu acceso."}
          </p>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <form className="space-y-4" onSubmit={onSubmit}>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-gray-700">Email</label>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="block w-full rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                placeholder="tu@empresa.com"
                required
                disabled={mode === "setup"}
              />
            </div>
            {mode === "setup" && (
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">Nombre</label>
                <input
                  type="text"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  className="block w-full rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  placeholder="Tu nombre"
                />
              </div>
            )}
            {mode !== "requestSetup" && (
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className="block w-full rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  placeholder="••••••••"
                  required
                  minLength={mode === "setup" ? 8 : undefined}
                />
              </div>
            )}
            {mode === "setup" && (
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">Repetir password</label>
                <input
                  type="password"
                  value={passwordConfirmation}
                  onChange={(event) => setPasswordConfirmation(event.target.value)}
                  className="block w-full rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  placeholder="••••••••"
                  required
                  minLength={8}
                />
              </div>
            )}
            {error && (
              <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
            )}
            <button
              className="flex w-full items-center justify-center rounded-lg bg-primary-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50"
              disabled={submitting}
              type="submit"
            >
              {submitting ? (
                <>
                  <div className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  Ingresando...
                </>
              ) : (
                mode === "login" ? "Entrar" : mode === "requestSetup" ? "Continuar" : "Crear clave"
              )}
            </button>
          </form>
          <button
            className="mt-4 w-full rounded-lg px-3 py-2 text-sm font-medium text-primary-700 transition hover:bg-primary-50"
            onClick={() => {
              setError("");
              setPassword("");
              setPasswordConfirmation("");
              setMode(mode === "login" ? "requestSetup" : "login");
            }}
            type="button"
          >
            {mode === "login" ? "No tengo clave aún" : "Volver al login"}
          </button>
        </div>
      </div>
    </main>
  );
}
