"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { ChevronDown, MoreHorizontal, Plus, X } from "lucide-react";

import { DataTable } from "@/components/data-table";
import { Badge } from "@/components/badge";
import { ProtectedPage } from "@/components/protected-page";
import { SectionCard } from "@/components/section-card";
import { Shell } from "@/components/shell";
import { TableSkeleton } from "@/components/table-skeleton";
import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api";
import { useAutoRefresh } from "@/lib/use-auto-refresh";
import type { Company, Employee } from "@/lib/types";

const COUNTRY_OPTIONS = [
  { code: "+56", flag: "🇨🇱", label: "Chile" },
  { code: "+54", flag: "🇦🇷", label: "Argentina" },
  { code: "+51", flag: "🇵🇪", label: "Peru" },
  { code: "+57", flag: "🇨🇴", label: "Colombia" },
  { code: "+52", flag: "🇲🇽", label: "Mexico" },
  { code: "+1", flag: "🇺🇸", label: "Estados Unidos" },
];

const ACCOUNT_TYPE_OPTIONS = [
  "Cuenta Corriente",
  "Cuenta Vista",
  "Cuenta de Ahorro",
  "Chequera Electronica",
];

const emptyForm = {
  phone_country_code: "+56",
  phone_number: "",
  first_name: "",
  last_name: "",
  rut: "",
  email: "",
  company_id: "",
  bank_name: "",
  account_type: "",
  account_number: "",
  account_holder: "",
  account_holder_rut: "",
  active: true,
  last_activity_at: "",
};

const fieldLabels: Record<string, string> = {
  first_name: "Nombre",
  last_name: "Apellido",
  rut: "RUT",
  email: "Email",
  bank_name: "Banco",
  account_type: "Tipo de cuenta",
  account_number: "Número de cuenta",
  account_holder: "Titular",
  account_holder_rut: "RUT titular",
};

function buildPhoneValue(countryCode: string, phoneNumber: string): string {
  const normalizedCountryCode = String(countryCode || "").replace(/[^\d+]/g, "");
  const normalizedPhoneNumber = String(phoneNumber || "").replace(/\D/g, "");
  return `${normalizedCountryCode}${normalizedPhoneNumber}`;
}

function splitPhoneValue(phone: string): { phone_country_code: string; phone_number: string } {
  const normalized = String(phone || "").trim();
  const matchedOption = COUNTRY_OPTIONS.find((option) => normalized.startsWith(option.code));
  if (matchedOption) {
    return {
      phone_country_code: matchedOption.code,
      phone_number: normalized.slice(matchedOption.code.length),
    };
  }
  return {
    phone_country_code: "+56",
    phone_number: normalized.replace(/^\+/, ""),
  };
}

export default function EmployeesPage() {
  const { token } = useAuth();
  const [items, setItems] = useState<Employee[] | null>(null);
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [companyAccordionOpen, setCompanyAccordionOpen] = useState(false);
  const [deleteModal, setDeleteModal] = useState<{
    phone: string;
    name: string;
    deleteCases: boolean;
  } | null>(null);
  const [deleting, setDeleting] = useState(false);

  function load() {
    if (!token) {
      return;
    }
    Promise.all([
      apiRequest<{ items: Employee[] }>("/employees", { token }),
      apiRequest<{ items: Company[] }>("/companies", { token }),
    ])
      .then(([employeesData, companiesData]) => {
        setItems(employeesData.items);
        setCompanies(companiesData.items.filter((company) => company.active));
      })
      .catch((nextError) => setError(nextError.message));
  }

  useEffect(() => {
    load();
  }, [token]);

  useAutoRefresh(
    () => load(),
    {
      enabled:
        Boolean(token) &&
        !submitting &&
        !createOpen &&
        !deleting &&
        !deleteModal,
    },
  );

  const selectedCompany = useMemo(
    () => companies?.find((company) => company.company_id === form.company_id) || null,
    [companies, form.company_id],
  );

  const hasOptionalBankData = Boolean(
    form.bank_name ||
      form.account_type ||
      form.account_number ||
      form.account_holder ||
      form.account_holder_rut,
  );

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await apiRequest("/employees", {
        method: "POST",
        body: {
          ...form,
          phone: buildPhoneValue(form.phone_country_code, form.phone_number),
        },
        token,
      });
      setForm(emptyForm);
      setCreateOpen(false);
      setCompanyAccordionOpen(false);
      load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "No se pudo crear la persona.");
    } finally {
      setSubmitting(false);
    }
  }

  async function deactivate(phone: string) {
    if (!token) {
      return;
    }
    setError("");
    try {
      await apiRequest(`/employees/${encodeURIComponent(phone)}/actions`, {
        method: "POST",
        body: { action: "deactivate" },
        token,
      });
      load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "No se pudo desactivar la persona.");
    }
  }

  async function activate(phone: string) {
    if (!token) {
      return;
    }
    setError("");
    try {
      await apiRequest(`/employees/${encodeURIComponent(phone)}/actions`, {
        method: "POST",
        body: { action: "activate" },
        token,
      });
      load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "No se pudo activar la persona.");
    }
  }

  async function removeEmployee() {
    if (!token || !deleteModal) {
      return;
    }
    setDeleting(true);
    setError("");
    try {
      const query = deleteModal.deleteCases ? "?delete_cases=true" : "";
      await apiRequest(`/employees/${encodeURIComponent(deleteModal.phone)}${query}`, {
        method: "DELETE",
        token,
      });
      setDeleteModal(null);
      load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "No se pudo eliminar la persona.");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <ProtectedPage>
      <Shell title="Personas" description="Gestión operativa de personas registradas en WhatsApp.">
        {createOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/40 px-4">
            <div className="flex max-h-[85vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-2xl">
              <div className="flex shrink-0 items-center justify-between border-b border-gray-100 px-5 py-4">
                <div>
                  <h2 className="text-base font-semibold text-gray-900">Crear persona</h2>
                  <p className="text-sm text-gray-500">Agrega un nuevo usuario operativo al sistema.</p>
                </div>
                <button
                  className="rounded-lg p-2 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700"
                  onClick={() => {
                    setCreateOpen(false);
                    setForm(emptyForm);
                    setCompanyAccordionOpen(false);
                  }}
                  type="button"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <form className="flex min-h-0 flex-1 flex-col" onSubmit={onSubmit}>
                <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
                  <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">
                    Empresa
                  </label>
                  <div className="rounded-xl border border-gray-200 bg-gray-50">
                    <button
                      type="button"
                      onClick={() => setCompanyAccordionOpen((current) => !current)}
                      className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
                    >
                      <span className="min-w-0">
                        <span className="block text-sm font-medium text-gray-900">
                          {selectedCompany?.name || "Selecciona una empresa"}
                        </span>
                        <span className="block truncate text-xs text-gray-500">
                          {selectedCompany
                            ? `${selectedCompany.company_id} · ${selectedCompany.rut || "Sin RUT"}`
                            : "Usa la lista de empresas existentes"}
                        </span>
                      </span>
                      <ChevronDown
                        className={`h-4 w-4 shrink-0 text-gray-500 transition ${companyAccordionOpen ? "rotate-180" : ""}`}
                      />
                    </button>
                    {companyAccordionOpen && (
                      <div className="border-t border-gray-200 bg-white px-2 py-2">
                        <div className="max-h-52 space-y-1 overflow-y-auto">
                          {(companies || []).map((company) => (
                            <button
                              key={company.company_id}
                              type="button"
                              onClick={() => {
                                setForm((current) => ({
                                  ...current,
                                  company_id: company.company_id,
                                }));
                                setCompanyAccordionOpen(false);
                              }}
                              className={`w-full rounded-lg px-3 py-2 text-left transition ${
                                form.company_id === company.company_id
                                  ? "bg-primary-50 text-primary-700"
                                  : "hover:bg-gray-50"
                              }`}
                            >
                              <span className="block text-sm font-medium">
                                {company.name}
                              </span>
                              <span className="block text-xs text-gray-500">
                                {company.company_id} · {company.rut || "Sin RUT"}
                              </span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">
                    {fieldLabels.rut}
                  </label>
                  <input
                    value={form.rut}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, rut: event.target.value }))
                    }
                    className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">
                    {fieldLabels.first_name}
                  </label>
                  <input
                    value={form.first_name}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, first_name: event.target.value }))
                    }
                    className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">
                    {fieldLabels.last_name}
                  </label>
                  <input
                    value={form.last_name}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, last_name: event.target.value }))
                    }
                    className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">
                    Teléfono
                  </label>
                  <div className="grid grid-cols-[180px_minmax(0,1fr)] gap-3">
                    <select
                      value={form.phone_country_code}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          phone_country_code: event.target.value,
                        }))
                      }
                      className="rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                    >
                      {COUNTRY_OPTIONS.map((option) => (
                        <option key={option.code} value={option.code}>
                          {`${option.flag} ${option.label} (${option.code})`}
                        </option>
                      ))}
                    </select>
                    <input
                      value={form.phone_number}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          phone_number: event.target.value.replace(/\D/g, ""),
                        }))
                      }
                      inputMode="numeric"
                      placeholder="Número telefónico"
                      className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                    />
                  </div>
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">
                    {fieldLabels.email}
                  </label>
                  <input
                    value={form.email}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, email: event.target.value }))
                    }
                    className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  />
                </div>
                <details
                  className="rounded-xl border border-gray-200 bg-gray-50"
                  open={hasOptionalBankData}
                >
                  <summary className="cursor-pointer list-none px-4 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <span>
                        <span className="block text-sm font-medium text-gray-900">
                          Datos bancarios
                        </span>
                        <span className="block text-xs text-gray-500">
                          Opcional, para registrar información de pago.
                        </span>
                      </span>
                      <ChevronDown className="h-4 w-4 text-gray-500" />
                    </div>
                  </summary>
                  <div className="grid gap-4 border-t border-gray-200 bg-white p-4">
                    <div>
                      <label className="mb-1.5 block text-sm font-medium text-gray-700">
                        {fieldLabels.bank_name}
                      </label>
                      <input
                        value={form.bank_name}
                        onChange={(event) =>
                          setForm((current) => ({ ...current, bank_name: event.target.value }))
                        }
                        className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-sm font-medium text-gray-700">
                        {fieldLabels.account_type}
                      </label>
                      <select
                        value={form.account_type}
                        onChange={(event) =>
                          setForm((current) => ({ ...current, account_type: event.target.value }))
                        }
                        className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                      >
                        <option value="">Selecciona un tipo</option>
                        {ACCOUNT_TYPE_OPTIONS.map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </select>
                    </div>
                    {(["account_number", "account_holder", "account_holder_rut"] as const).map((field) => (
                      <div key={field}>
                        <label className="mb-1.5 block text-sm font-medium text-gray-700">
                          {fieldLabels[field]}
                        </label>
                        <input
                          value={form[field]}
                          onChange={(event) =>
                            setForm((current) => ({ ...current, [field]: event.target.value }))
                          }
                          className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                        />
                      </div>
                    ))}
                  </div>
                  </details>
                </div>
                <div className="flex shrink-0 items-center justify-end gap-3 border-t border-gray-100 px-5 py-4">
                  <button
                    className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                    onClick={() => {
                      setCreateOpen(false);
                      setForm(emptyForm);
                      setCompanyAccordionOpen(false);
                    }}
                    type="button"
                  >
                    Cancelar
                  </button>
                  <button
                    className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700 disabled:opacity-50"
                    type="submit"
                    disabled={
                      submitting ||
                      !form.first_name.trim() ||
                      !form.last_name.trim() ||
                      !form.company_id.trim() ||
                      !form.phone_number.trim()
                    }
                  >
                    {submitting ? "Creando..." : "Crear persona"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
        {deleteModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/40 px-4">
            <div className="w-full max-w-xl rounded-2xl border border-gray-200 bg-white shadow-2xl">
              <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
                <div>
                  <h2 className="text-base font-semibold text-gray-900">Eliminar persona</h2>
                  <p className="text-sm text-gray-500">
                    Esta acción eliminará a {deleteModal.name || deleteModal.phone} del sistema.
                  </p>
                </div>
                <button
                  className="rounded-lg p-2 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700"
                  onClick={() => {
                    if (deleting) {
                      return;
                    }
                    setDeleteModal(null);
                  }}
                  type="button"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="space-y-4 p-5">
                <p className="text-sm text-gray-600">
                  Puedes elegir si también quieres eliminar los casos de la persona. Si haces eso,
                  también se eliminarán sus gastos asociados.
                </p>
                <label className="flex items-start gap-3 rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
                  <input
                    checked={deleteModal.deleteCases}
                    className="mt-1 h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                    onChange={(event) =>
                      setDeleteModal((current) =>
                        current
                          ? { ...current, deleteCases: event.target.checked }
                          : current
                      )
                    }
                    type="checkbox"
                  />
                  <span>
                    <span className="block text-sm font-medium text-gray-900">
                      Eliminar también los casos de esta persona
                    </span>
                    <span className="block text-sm text-gray-500">
                      Al marcar esta opción, también se eliminarán los gastos relacionados.
                    </span>
                  </span>
                </label>
                <div className="flex items-center justify-end gap-3 pt-2">
                  <button
                    className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                    onClick={() => setDeleteModal(null)}
                    disabled={deleting}
                    type="button"
                  >
                    Cancelar
                  </button>
                  <button
                    className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-red-700 disabled:opacity-50"
                    onClick={removeEmployee}
                    disabled={deleting}
                    type="button"
                  >
                    {deleting ? "Eliminando..." : "Eliminar persona"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
        {error && (
          <div className="mb-6 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        )}
        <SectionCard
          title="Listado"
          action={
            <button
              className="flex h-9 w-9 items-center justify-center rounded-full bg-primary-600 text-white shadow-sm transition hover:bg-primary-700"
              onClick={() => {
                setError("");
                setCreateOpen(true);
              }}
              type="button"
            >
              <Plus className="h-5 w-5" />
            </button>
          }
        >
          {items === null ? (
            <TableSkeleton columns={7} rows={5} />
          ) : (
            <DataTable
              columns={["Nombre", "Teléfono", "RUT", "Empresa", "Gastos", "Estado", ""]}
              rowHrefs={items.map((employee) => `/employees/${encodeURIComponent(employee.phone)}`)}
              rows={items.map((employee) => [
                <span key="name" className="font-medium text-gray-900">
                  {employee.first_name || employee.last_name
                    ? `${employee.first_name || ""} ${employee.last_name || ""}`.trim()
                    : employee.name}
                </span>,
                <span key="phone" className="font-mono text-xs">{employee.phone}</span>,
                employee.rut || "-",
                employee.company_id || "-",
                employee.expense_count ?? 0,
                <Badge key="state">{employee.active ? "active" : "inactive"}</Badge>,
                <div className="flex items-center justify-end gap-2" key="actions">
                  <Link
                    className="text-sm font-medium text-blue-600 transition hover:text-blue-700"
                    href={`/expenses?employee_phone=${encodeURIComponent(employee.phone)}`}
                  >
                    Ver gastos
                  </Link>
                  <details className="relative">
                    <summary className="flex h-9 w-9 cursor-pointer list-none items-center justify-center rounded-full text-gray-500 transition hover:bg-slate-100 hover:text-gray-700 [&::-webkit-details-marker]:hidden">
                      <MoreHorizontal className="h-4 w-4" />
                    </summary>
                    <div className="absolute right-0 top-11 z-10 min-w-[11rem] overflow-hidden rounded-xl border border-gray-200 bg-white py-1 shadow-lg">
                      <Link
                        href={`/employees/${encodeURIComponent(employee.phone)}`}
                        className="block px-4 py-2 text-sm text-gray-700 transition hover:bg-slate-50 hover:text-gray-900"
                      >
                        Editar
                      </Link>
                      {employee.active ? (
                        <button
                          className="block w-full px-4 py-2 text-left text-sm text-gray-700 transition hover:bg-slate-50 hover:text-red-600"
                          onClick={() => deactivate(employee.phone)}
                          type="button"
                        >
                          Desactivar
                        </button>
                      ) : (
                        <button
                          className="block w-full px-4 py-2 text-left text-sm text-gray-700 transition hover:bg-slate-50 hover:text-blue-700"
                          onClick={() => activate(employee.phone)}
                          type="button"
                        >
                          Activar
                        </button>
                      )}
                      <button
                        className="block w-full px-4 py-2 text-left text-sm text-gray-700 transition hover:bg-red-50 hover:text-red-700"
                        onClick={() =>
                          setDeleteModal({
                            phone: employee.phone,
                            name: employee.first_name || employee.last_name
                              ? `${employee.first_name || ""} ${employee.last_name || ""}`.trim()
                              : employee.name,
                            deleteCases: false,
                          })
                        }
                        type="button"
                      >
                        Eliminar
                      </button>
                    </div>
                  </details>
                </div>,
              ])}
            />
          )}
        </SectionCard>
      </Shell>
    </ProtectedPage>
  );
}
