"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { KeyRound, Plus, UserPlus } from "lucide-react";

import { ProtectedPage } from "@/components/protected-page";
import { SectionCard } from "@/components/section-card";
import { Shell } from "@/components/shell";
import { TableSkeleton } from "@/components/table-skeleton";
import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api";
import type { BackofficeUser, Company } from "@/lib/types";

const emptyForm = {
  name: "",
  email: "",
  role: "company_admin",
  scope_type: "company",
  company_id: "",
};

function roleLabel(role: string): string {
  const labels: Record<string, string> = {
    super_admin: "Super admin",
    admin: "Admin",
    company_admin: "Admin empresa",
    operator: "Operador",
  };
  return labels[role] || role;
}

export default function UsersPage() {
  const { token, user } = useAuth();
  const [items, setItems] = useState<BackofficeUser[] | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [createOpen, setCreateOpen] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const isGlobalAdmin = user?.scope_type === "global";

  function load() {
    if (!token) {
      return;
    }
    Promise.all([
      apiRequest<{ items: BackofficeUser[] }>("/users", { token }),
      apiRequest<{ items: Company[] }>("/companies", { token }),
    ])
      .then(([usersData, companiesData]) => {
        setItems(usersData.items);
        setCompanies(companiesData.items.filter((company) => company.active));
      })
      .catch((nextError) => setError(nextError.message));
  }

  useEffect(() => {
    load();
  }, [token]);

  const visibleCompanies = useMemo(() => {
    if (isGlobalAdmin) {
      return companies;
    }
    const allowed = new Set((user?.company_ids || []).map((companyId) => companyId.toLowerCase()));
    return companies.filter((company) => allowed.has(company.company_id.toLowerCase()));
  }, [companies, isGlobalAdmin, user?.company_ids]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await apiRequest("/users", {
        method: "POST",
        token,
        body: {
          ...form,
          scope_type: isGlobalAdmin ? form.scope_type : "company",
          company_id: form.scope_type === "global" ? "" : form.company_id,
          company_ids: form.scope_type === "global" || !form.company_id ? [] : [form.company_id],
        },
      });
      setForm(emptyForm);
      setCreateOpen(false);
      load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "No se pudo crear el usuario.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ProtectedPage>
      <Shell
        title="Usuarios"
        description="Crea accesos de backoffice y revisa quién ya activó su clave."
      >
        <div className="space-y-5">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <SectionCard
            title="Accesos"
            action={
              <button
                className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700"
                onClick={() => setCreateOpen((value) => !value)}
                type="button"
              >
                <Plus className="h-4 w-4" />
                Crear usuario
              </button>
            }
          >
            {createOpen && (
              <form className="mb-6 grid gap-4 rounded-lg border border-gray-200 bg-gray-50 p-4 md:grid-cols-2" onSubmit={onSubmit}>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">Nombre</label>
                  <input
                    className="block w-full rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                    onChange={(event) => setForm({ ...form, name: event.target.value })}
                    placeholder="Nombre del usuario"
                    type="text"
                    value={form.name}
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">Email</label>
                  <input
                    className="block w-full rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                    onChange={(event) => setForm({ ...form, email: event.target.value })}
                    placeholder="usuario@empresa.com"
                    required
                    type="email"
                    value={form.email}
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">Rol</label>
                  <select
                    className="block w-full rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                    onChange={(event) => setForm({ ...form, role: event.target.value })}
                    value={form.role}
                  >
                    {isGlobalAdmin && <option value="super_admin">Super admin</option>}
                    <option value="company_admin">Admin empresa</option>
                    <option value="operator">Operador</option>
                  </select>
                </div>
                {isGlobalAdmin && (
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Alcance</label>
                    <select
                      className="block w-full rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                      onChange={(event) => setForm({ ...form, scope_type: event.target.value })}
                      value={form.scope_type}
                    >
                      <option value="company">Empresa</option>
                      <option value="global">Global</option>
                    </select>
                  </div>
                )}
                {form.scope_type !== "global" && (
                  <div className="md:col-span-2">
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Empresa</label>
                    <select
                      className="block w-full rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                      onChange={(event) => setForm({ ...form, company_id: event.target.value })}
                      value={form.company_id}
                    >
                      <option value="">Usar empresa permitida por defecto</option>
                      {visibleCompanies.map((company) => (
                        <option key={company.company_id} value={company.company_id}>
                          {company.name || company.company_id}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                <div className="flex items-center gap-3 md:col-span-2">
                  <button
                    className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700 disabled:opacity-50"
                    disabled={submitting}
                    type="submit"
                  >
                    <UserPlus className="h-4 w-4" />
                    {submitting ? "Creando..." : "Crear acceso"}
                  </button>
                  <button
                    className="rounded-lg border border-gray-200 px-4 py-2.5 text-sm font-semibold text-gray-700 transition hover:bg-white"
                    onClick={() => setCreateOpen(false)}
                    type="button"
                  >
                    Cancelar
                  </button>
                </div>
              </form>
            )}

            {!items ? (
              <TableSkeleton rows={6} columns={5} />
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 text-sm">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600">Usuario</th>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600">Rol</th>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600">Alcance</th>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600">Clave</th>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600">Estado</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 bg-white">
                    {items.map((item) => (
                      <tr key={item.id}>
                        <td className="px-4 py-3">
                          <div className="font-medium text-gray-900">{item.name || item.email}</div>
                          <div className="text-xs text-gray-500">{item.email}</div>
                        </td>
                        <td className="px-4 py-3 text-gray-700">{roleLabel(item.role)}</td>
                        <td className="px-4 py-3 text-gray-700">
                          {item.scope_type === "global"
                            ? "Global"
                            : (item.company_ids || []).join(", ") || item.company_id || "Empresa"}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
                              item.has_password
                                ? "bg-green-50 text-green-700 ring-1 ring-green-600/20"
                                : "bg-amber-50 text-amber-700 ring-1 ring-amber-600/20"
                            }`}
                          >
                            <KeyRound className="h-3.5 w-3.5" />
                            {item.has_password ? "Activa" : "Pendiente"}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={item.active ? "text-green-700" : "text-gray-500"}>
                            {item.active ? "Activo" : "Inactivo"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>
        </div>
      </Shell>
    </ProtectedPage>
  );
}
