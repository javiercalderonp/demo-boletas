"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  CircleDashed,
  Download,
  Landmark,
  Plus,
  Search,
  Send,
  X,
} from "lucide-react";

import { DataTable } from "@/components/data-table";
import { Badge } from "@/components/badge";
import { ProtectedPage } from "@/components/protected-page";
import { SectionCard } from "@/components/section-card";
import { Shell } from "@/components/shell";
import { TableSkeleton } from "@/components/table-skeleton";
import { useAuth } from "@/components/auth-provider";
import { apiRequest, getApiBaseUrl } from "@/lib/api";
import { useAutoRefresh } from "@/lib/use-auto-refresh";
import type { CaseItem, Company, Employee } from "@/lib/types";

const emptyForm = {
  employee_phone: "",
  context_label: "",
  company_id: "",
  closure_method: "docusign",
  status: "active",
  fondos_entregados: "",
  notes: "",
};

const emptyEmployeeForm = {
  phone: "",
  name: "",
  rut: "",
  email: "",
  company_id: "",
  active: true,
  last_activity_at: "",
};

const fieldLabels: Record<string, string> = {
  context_label: "Nombre de la rendición",
  company_id: "Empresa",
  closure_method: "Método de cierre",
  fondos_entregados: "Fondos entregados (CLP)",
};

const closureMethodLabels: Record<string, string> = {
  docusign: "DocuSign",
  simple: "Cierre Simple",
};

const rendicionStatusLabels: Record<string, string> = {
  open: "Abierta",
  pending_user_confirmation: "Esperando confirmación",
  approved: "Aprobada",
  closed: "Cerrada",
};

const rendicionStatusTone: Record<string, string> = {
  open: "open",
  pending_user_confirmation: "pending_user_confirmation",
  approved: "approved",
  closed: "closed",
};

const actionButtonClassName =
  "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-semibold shadow-sm transition disabled:cursor-not-allowed disabled:opacity-50";

function formatCLP(value?: number | string): string {
  const num = typeof value === "string" ? parseFloat(value) : value;
  if (num == null || isNaN(num)) return "-";
  return `$${num.toLocaleString("es-CL", { maximumFractionDigits: 0 })}`;
}

function normalizeMoneyInput(value: string): string {
  return value.replace(/\D/g, "");
}

function formatMoneyInput(value: string): string {
  const normalized = normalizeMoneyInput(value);
  if (!normalized) return "";
  return `$ ${Number(normalized).toLocaleString("es-CL", { maximumFractionDigits: 0 })}`;
}

function renderActionButton({
  icon,
  label,
  loadingLabel,
  loading,
  onClick,
  className,
}: {
  icon: React.ReactNode;
  label: string;
  loadingLabel: string;
  loading: boolean;
  onClick: () => void;
  className: string;
}) {
  return (
    <button
      className={className}
      onClick={onClick}
      disabled={loading}
      type="button"
    >
      {icon}
      {loading ? loadingLabel : label}
    </button>
  );
}

function getCaseActionConfig(item: CaseItem) {
  if (item.rendicion_status === "open") {
    const isSimpleClosure = item.closure_method === "simple";
    return {
      action: "request_user_confirmation" as const,
      icon: <Send className="h-3.5 w-3.5" />,
      label: isSimpleClosure ? "Pedir confirmación" : "Pedir firma",
      loadingLabel: "Enviando...",
      className:
        "border-primary-200 bg-primary-50 text-primary-700 hover:border-primary-300 hover:bg-primary-100",
    };
  }

  if (
    item.rendicion_status === "approved" &&
    item.settlement_status === "settlement_pending"
  ) {
    return {
      action: "resolve_settlement" as const,
      icon: <Landmark className="h-3.5 w-3.5" />,
      label: "Liquidación resuelta",
      loadingLabel: "Registrando...",
      className:
        "border-sky-200 bg-sky-50 text-sky-700 hover:border-sky-300 hover:bg-sky-100",
    };
  }

  if (
    item.rendicion_status === "approved" &&
    item.settlement_status !== "settlement_pending" &&
    item.status !== "closed"
  ) {
    return {
      action: "close_rendicion" as const,
      icon: <CircleDashed className="h-3.5 w-3.5" />,
      label: "Cerrar rendición",
      loadingLabel: "Cerrando...",
      className:
        "border-gray-300 bg-gray-100 text-gray-700 hover:border-gray-400 hover:bg-gray-200",
    };
  }

  return null;
}

function parseActiveCaseConflict(message: string): {
  activeCaseLabel: string;
  activeCaseId: string;
} | null {
  if (!/ya tiene un caso activo/i.test(message)) {
    return null;
  }

  const afterMarker = message.split(/caso activo:\s*/i)[1] || "";
  const reference = afterMarker.split(/\.\s*debes cerrarlo/i)[0]?.trim() || "";
  const idMatch = reference.match(/\(([^)]+)\)\s*$/);
  const activeCaseId = (idMatch?.[1] || "").trim();
  const activeCaseLabel = reference.replace(/\s*\([^)]+\)\s*$/, "").trim();

  return {
    activeCaseLabel: activeCaseLabel || reference || "Caso activo",
    activeCaseId,
  };
}

export default function CasesPage() {
  const { token } = useAuth();
  const [items, setItems] = useState<CaseItem[] | null>(null);
  const [employees, setEmployees] = useState<Employee[] | null>(null);
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [employeeForm, setEmployeeForm] = useState(emptyEmployeeForm);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [creatingEmployee, setCreatingEmployee] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createEmployeeOpen, setCreateEmployeeOpen] = useState(false);
  const [companyAccordionOpen, setCompanyAccordionOpen] = useState(false);
  const [createConflictPopup, setCreateConflictPopup] = useState<{
    message: string;
    activeCaseLabel: string;
    activeCaseId: string;
  } | null>(null);
  const [employeeSearch, setEmployeeSearch] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [balanceFilter, setBalanceFilter] = useState<"" | "positive" | "negative">("");
  const [actionPopup, setActionPopup] = useState<{ title: string; message: string } | null>(null);
  const [actionLoading, setActionLoading] = useState("");

  async function exportCsv() {
    if (!token) return;
    const response = await fetch(`${getApiBaseUrl()}/cases/export/csv`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "rendiciones.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  function load() {
    if (!token) return;
    Promise.all([
      apiRequest<{ items: CaseItem[] }>("/cases", { token }),
      apiRequest<{ items: Employee[] }>("/employees", { token }),
      apiRequest<{ items: Company[] }>("/companies", { token }),
    ])
      .then(([casesData, employeesData, companiesData]) => {
        setItems(casesData.items);
        setEmployees(employeesData.items);
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
        !creatingEmployee &&
        !createOpen &&
        !createEmployeeOpen &&
        !actionLoading,
    },
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    setSearchQuery(params.get("q") || "");
    setStatusFilter(params.get("status") || "");
    const balance = params.get("balance");
    setBalanceFilter(
      balance === "positive" || balance === "negative" ? balance : "",
    );
  }, []);

  const selectedCompany = useMemo(
    () => companies?.find((company) => company.company_id === form.company_id) || null,
    [companies, form.company_id],
  );

  function employeeMatchesCompany(employee: Employee, companyId: string): boolean {
    if (!companyId.trim()) {
      return true;
    }
    return (employee.company_id || "").trim() === companyId.trim();
  }

  const employeeOptions = useMemo(() => {
    const normalizedQuery = employeeSearch.trim().toLowerCase();
    const source = [...(employees || [])]
      .filter((employee) => employeeMatchesCompany(employee, form.company_id))
      .sort((a, b) => a.name.localeCompare(b.name, "es-CL"));
    if (!normalizedQuery) {
      return source;
    }
    return source.filter((employee) => {
      const label = `${employee.name} ${employee.phone} ${employee.company_id || ""}`.toLowerCase();
      return label.includes(normalizedQuery);
    });
  }, [employees, employeeSearch, form.company_id]);

  const selectedEmployee = useMemo(
    () => (employees || []).find((employee) => employee.phone === form.employee_phone) || null,
    [employees, form.employee_phone],
  );

  useEffect(() => {
    if (!selectedEmployee) return;
    if (employeeMatchesCompany(selectedEmployee, form.company_id)) return;
    setForm((current) => ({
      ...current,
      employee_phone: "",
    }));
    setEmployeeSearch("");
  }, [form.company_id, selectedEmployee]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    setSubmitting(true);
    setError("");
    try {
      await apiRequest("/cases", { method: "POST", body: form, token });
      setForm(emptyForm);
      setEmployeeSearch("");
      setEmployeeForm(emptyEmployeeForm);
      setCreateEmployeeOpen(false);
      setCreateOpen(false);
      setCompanyAccordionOpen(false);
      load();
    } catch (nextError) {
      const message =
        nextError instanceof Error
          ? nextError.message
          : "No se pudo crear la rendición.";
      const conflict = parseActiveCaseConflict(message);
      if (conflict) {
        setCreateConflictPopup({
          message,
          activeCaseLabel: conflict.activeCaseLabel,
          activeCaseId: conflict.activeCaseId,
        });
        setError("");
      } else {
        setError(message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function onCreateEmployee() {
    if (!token) return;
    setCreatingEmployee(true);
    setError("");
    try {
      const created = await apiRequest<Employee>("/employees", {
        method: "POST",
        body: employeeForm,
        token,
      });
      setEmployees((current) => {
        const next = [...(current || []).filter((item) => item.phone !== created.phone), created];
        next.sort((a, b) => a.name.localeCompare(b.name, "es-CL"));
        return next;
      });
      setForm((current) => ({
        ...current,
        company_id: created.company_id || current.company_id,
        employee_phone: created.phone,
      }));
      setEmployeeSearch(created.name);
      setEmployeeForm(emptyEmployeeForm);
      setCreateEmployeeOpen(false);
    } catch (nextError) {
      setError(
        nextError instanceof Error
          ? nextError.message
          : "No se pudo crear la persona.",
      );
    } finally {
      setCreatingEmployee(false);
    }
  }

  const filteredItems = useMemo(() => {
    if (!items) return null;
    let result = items;

    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      result = result.filter(
        (c) =>
          c.case_id.toLowerCase().includes(q) ||
          (c.context_label || "").toLowerCase().includes(q) ||
          (c.employee?.name || "").toLowerCase().includes(q) ||
          (c.employee_phone || c.phone || "").includes(q) ||
          (c.company_id || "").toLowerCase().includes(q),
      );
    }

    if (statusFilter) {
      result = result.filter(
        (c) => (c.rendicion_status || c.status) === statusFilter,
      );
    }

    if (balanceFilter === "negative") {
      result = result.filter((c) => (c.saldo_restante ?? 0) < 0);
    } else if (balanceFilter === "positive") {
      result = result.filter((c) => (c.saldo_restante ?? 0) >= 0);
    }

    return result;
  }, [items, searchQuery, statusFilter, balanceFilter]);

  async function runAction(
    caseId: string,
    action:
      | "close"
      | "request_user_confirmation"
      | "resolve_settlement"
      | "close_rendicion",
  ) {
    if (!token) return;
    const loadingKey = `${caseId}:${action}`;
    setActionLoading(loadingKey);
    try {
      await apiRequest(`/cases/${caseId}/actions`, {
        method: "POST",
        body: { action },
        token,
      });
      load();
    } catch (nextError) {
      const message =
        nextError instanceof Error
          ? nextError.message
          : "No se pudo completar la acción sobre la rendición.";
      setActionPopup({
        title:
          action === "close_rendicion"
            ? "No se pudo cerrar la rendición"
            : "No se pudo completar la acción",
        message,
      });
    } finally {
      setActionLoading("");
    }
  }

  return (
    <ProtectedPage>
      <Shell
        title="Rendiciones"
        description="Fondos por rendir — expedientes activos y cerrados."
      >
        {actionPopup && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/40 px-4">
            <div
              aria-modal="true"
              role="dialog"
              className="w-full max-w-md rounded-2xl border border-red-100 bg-white shadow-2xl"
            >
              <div className="flex items-start justify-between gap-4 border-b border-gray-100 px-5 py-4">
                <div>
                  <h2 className="text-base font-semibold text-gray-900">
                    {actionPopup.title}
                  </h2>
                  <p className="mt-1 text-sm text-gray-500">
                    Revisa el estado de la rendición antes de volver a intentarlo.
                  </p>
                </div>
                <button
                  aria-label="Cerrar popup"
                  className="rounded-lg p-2 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700"
                  onClick={() => setActionPopup(null)}
                  type="button"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="px-5 py-4">
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {actionPopup.message}
                </div>
                <div className="mt-5 flex justify-end">
                  <button
                    className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700"
                    onClick={() => setActionPopup(null)}
                    type="button"
                  >
                    Entendido
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {createConflictPopup && (
          <div className="fixed inset-0 z-[120] flex items-center justify-center bg-gray-950/55 px-4 backdrop-blur-sm">
            <div
              aria-modal="true"
              role="alertdialog"
              className="w-full max-w-lg overflow-hidden rounded-[28px] border border-amber-200 bg-white shadow-[0_30px_90px_-30px_rgba(120,53,15,0.45)]"
            >
              <div className="relative border-b border-amber-100 bg-[radial-gradient(circle_at_top_left,_rgba(251,191,36,0.28),_transparent_45%),linear-gradient(135deg,_#fff7ed,_#ffffff_68%)] px-6 py-5">
                <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-amber-200 bg-white/85 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.24em] text-amber-700">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  Restricción activa
                </div>
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h2 className="text-xl font-semibold tracking-tight text-gray-950">
                      No se puede crear otra rendición
                    </h2>
                    <p className="mt-2 max-w-md text-sm leading-6 text-gray-600">
                      Esta persona ya tiene un caso abierto. Primero hay que cerrarlo o resolver ese conflicto.
                    </p>
                  </div>
                  <button
                    aria-label="Cerrar popup"
                    className="rounded-full border border-white/80 bg-white/80 p-2 text-gray-500 transition hover:bg-white hover:text-gray-800"
                    onClick={() => setCreateConflictPopup(null)}
                    type="button"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
              </div>
              <div className="space-y-4 px-6 py-5">
                <div className="rounded-2xl border border-amber-200 bg-amber-50/70 p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-700">
                    Caso activo detectado
                  </p>
                  <p className="mt-2 text-lg font-semibold text-gray-950">
                    {createConflictPopup.activeCaseLabel || "Caso sin nombre"}
                  </p>
                  {createConflictPopup.activeCaseId && (
                    <p className="mt-1 text-sm text-gray-600">
                      ID: {createConflictPopup.activeCaseId}
                    </p>
                  )}
                </div>
                <div className="rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm leading-6 text-gray-700">
                  {createConflictPopup.message}
                </div>
                <div className="flex justify-end">
                  <button
                    className="rounded-xl bg-gray-950 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-gray-800"
                    onClick={() => setCreateConflictPopup(null)}
                    type="button"
                  >
                    Entendido
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {createOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/40 px-4">
            <div className="w-full max-w-xl rounded-2xl border border-gray-200 bg-white shadow-2xl">
              <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
                <div>
                  <h2 className="text-base font-semibold text-gray-900">
                    Nueva rendición
                  </h2>
                  <p className="text-sm text-gray-500">
                    Crea un expediente de fondos por rendir para una persona.
                  </p>
                </div>
                <button
                  className="rounded-lg p-2 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700"
                  onClick={() => {
                    setCreateOpen(false);
                    setForm(emptyForm);
                    setEmployeeSearch("");
                    setEmployeeForm(emptyEmployeeForm);
                    setCreateEmployeeOpen(false);
                    setCompanyAccordionOpen(false);
                  }}
                  type="button"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <form className="space-y-4 p-5" onSubmit={onSubmit}>
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
                                setForm((current) => {
                                  const keepSelectedEmployee =
                                    !current.employee_phone ||
                                    employeeMatchesCompany(
                                      selectedEmployee || {
                                        ...emptyEmployeeForm,
                                        name: "",
                                        phone: current.employee_phone,
                                        active: true,
                                      },
                                      company.company_id,
                                    );
                                  return {
                                    ...current,
                                    company_id: company.company_id,
                                    employee_phone: keepSelectedEmployee ? current.employee_phone : "",
                                  };
                                });
                                if (
                                  selectedEmployee &&
                                  !employeeMatchesCompany(selectedEmployee, company.company_id)
                                ) {
                                  setEmployeeSearch("");
                                }
                                setCompanyAccordionOpen(false);
                              }}
                              className={`w-full rounded-lg px-3 py-2 text-left transition ${
                                form.company_id === company.company_id
                                  ? "bg-primary-50 text-primary-700"
                                  : "hover:bg-gray-50"
                              }`}
                            >
                              <span className="block text-sm font-medium">{company.name}</span>
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
                  <div className="mb-1.5 flex items-center justify-between gap-3">
                    <label className="block text-sm font-medium text-gray-700">
                      Persona
                    </label>
                    <button
                      type="button"
                      onClick={() => {
                        setCreateEmployeeOpen((current) => !current);
                        setEmployeeForm((current) => ({
                          ...emptyEmployeeForm,
                          ...current,
                          company_id: form.company_id || current.company_id,
                        }));
                      }}
                      className="text-sm font-medium text-primary-600 transition hover:text-primary-700"
                    >
                      {createEmployeeOpen ? "Ocultar alta" : "Agregar persona"}
                    </button>
                  </div>
                  <input
                    list="employee-options"
                    value={selectedEmployee ? selectedEmployee.name : employeeSearch}
                    onChange={(event) =>
                      {
                        const rawValue = event.target.value;
                        setEmployeeSearch(rawValue);
                        const nextEmployee = employeeOptions.find((employee) => {
                          const nameLabel = employee.name.trim().toLowerCase();
                          const searchValue = rawValue.trim().toLowerCase();
                          return (
                            employee.phone === rawValue ||
                            nameLabel === searchValue
                          );
                        });
                        setForm((current) => ({
                          ...current,
                          employee_phone: nextEmployee?.phone || "",
                          company_id: nextEmployee?.company_id || current.company_id,
                        }));
                      }
                    }
                    placeholder="Busca por nombre o teléfono"
                    className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  />
                  <datalist id="employee-options">
                    {employeeOptions.map((employee) => (
                      <option key={employee.phone} value={employee.name}>
                        {`${employee.name} · ${employee.phone} · ${employee.company_id || "Sin empresa"}`}
                      </option>
                    ))}
                  </datalist>
                  {selectedEmployee && (
                    <p className="mt-2 text-xs text-gray-500">
                      {selectedEmployee.name} · {selectedEmployee.company_id || "Sin empresa asignada"}
                    </p>
                  )}
                  {!selectedEmployee && form.employee_phone.trim() && (
                    <p className="mt-2 text-xs text-amber-700">
                      Elige una persona de la lista para autocompletar la empresa.
                    </p>
                  )}
                  {(employees || []).length === 0 && (
                    <p className="mt-2 text-xs text-amber-700">
                      No hay personas registradas. Puedes crear una aquí mismo.
                    </p>
                  )}
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">
                    {fieldLabels.context_label}
                  </label>
                  <input
                    value={form.context_label}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        context_label: event.target.value,
                      }))
                    }
                    placeholder="Ej: Rendición abril - oficina central"
                    className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">
                    {fieldLabels.closure_method}
                  </label>
                  <select
                    value={form.closure_method}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        closure_method: event.target.value,
                      }))
                    }
                    className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  >
                    {Object.entries(closureMethodLabels).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </div>
                {createEmployeeOpen && (
                  <div>
                    <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-4">
                      <p className="mb-3 text-sm font-medium text-gray-900">
                        Nueva persona
                      </p>
                      <div className="space-y-3">
                        {(["name", "phone", "rut", "email"] as const).map((field) => (
                          <div key={field}>
                            <label className="mb-1.5 block text-sm font-medium text-gray-700">
                              {{
                                name: "Nombre",
                                phone: "Teléfono",
                                rut: "RUT",
                                email: "Email",
                              }[field]}
                            </label>
                            <input
                              value={employeeForm[field]}
                              onChange={(event) =>
                                setEmployeeForm((current) => ({
                                  ...current,
                                  [field]: event.target.value,
                                  company_id: form.company_id,
                                }))
                              }
                              className="block w-full rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                            />
                          </div>
                        ))}
                        <div>
                          <label className="mb-1.5 block text-sm font-medium text-gray-700">
                            Empresa
                          </label>
                          <input
                            value={employeeForm.company_id}
                            onChange={(event) =>
                              setEmployeeForm((current) => ({
                                ...current,
                                company_id: event.target.value,
                              }))
                            }
                            className="block w-full rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                          />
                        </div>
                        <div className="flex items-center justify-end gap-3 pt-1">
                          <button
                            className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-100"
                            type="button"
                            onClick={() => {
                              setCreateEmployeeOpen(false);
                              setEmployeeForm(emptyEmployeeForm);
                            }}
                          >
                            Cancelar alta
                          </button>
                          <button
                            className="rounded-lg bg-gray-900 px-3 py-2 text-sm font-semibold text-white transition hover:bg-gray-800 disabled:opacity-50"
                            type="button"
                            onClick={onCreateEmployee}
                            disabled={
                              creatingEmployee ||
                              !employeeForm.company_id.trim() ||
                              !employeeForm.name.trim() ||
                              !employeeForm.phone.trim()
                            }
                          >
                            {creatingEmployee ? "Creando..." : "Crear persona"}
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
                {(["fondos_entregados"] as const).map((field) => (
                  <div key={field}>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">
                      {fieldLabels[field]}
                    </label>
                    <input
                      value={formatMoneyInput(form[field])}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          [field]: normalizeMoneyInput(event.target.value),
                        }))
                      }
                      inputMode="numeric"
                      placeholder="$ 0"
                      className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                    />
                  </div>
                ))}
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">
                    Notas
                  </label>
                  <textarea
                    value={form.notes}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        notes: event.target.value,
                      }))
                    }
                    rows={3}
                    className="block w-full resize-none rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  />
                </div>
                <div className="flex items-center justify-end gap-3 pt-2">
                  <button
                    className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                    onClick={() => {
                      setCreateOpen(false);
                      setForm(emptyForm);
                      setEmployeeSearch("");
                      setEmployeeForm(emptyEmployeeForm);
                      setCreateEmployeeOpen(false);
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
                      !form.company_id.trim() ||
                      !form.employee_phone.trim() ||
                      !selectedEmployee ||
                      !form.context_label.trim()
                    }
                  >
                    {submitting ? "Creando..." : "Crear rendición"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
        {error && (
          <div className="mb-6 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        {/* Search and filters */}
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[200px] max-w-md">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="Buscar por empleado, ID o empresa..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="block w-full rounded-lg border border-gray-300 py-2 pl-9 pr-3 text-sm text-gray-900 outline-none transition placeholder:text-gray-400 focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
          >
            <option value="">Todos los estados</option>
            {Object.entries(rendicionStatusLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <select
            value={balanceFilter}
            onChange={(e) =>
              setBalanceFilter(e.target.value as "" | "positive" | "negative")
            }
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
          >
            <option value="">Todos los saldos</option>
            <option value="positive">Saldo positivo</option>
            <option value="negative">Saldo negativo</option>
          </select>
          {(searchQuery || statusFilter || balanceFilter) && (
            <button
              type="button"
              onClick={() => {
                setSearchQuery("");
                setStatusFilter("");
                setBalanceFilter("");
              }}
              className="text-xs text-gray-500 underline hover:text-gray-700"
            >
              Limpiar filtros
            </button>
          )}
          <button
            onClick={() => {
              void exportCsv();
            }}
            className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            type="button"
          >
            <Download className="h-4 w-4" />
            Exportar CSV
          </button>
        </div>

        <SectionCard
          title={`Listado${filteredItems ? ` (${filteredItems.length})` : ""}`}
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
          {filteredItems === null ? (
            <TableSkeleton columns={6} rows={5} />
          ) : (
            <DataTable
              columns={[
                "Estado",
                "Rendición",
                "Empleado",
                "Fondos",
                "Aprobado",
                "Saldo",
              ]}
              rowHrefs={filteredItems.map((item) => `/cases/${item.case_id}`)}
              rows={filteredItems.map((item) => {
                const actionConfig = getCaseActionConfig(item);
                return [
                  <div key="status" className="min-w-[128px] pt-0.5">
                    <Badge tone={rendicionStatusTone[item.rendicion_status || item.status]}>
                      {rendicionStatusLabels[item.rendicion_status || item.status] ||
                        item.rendicion_status ||
                        item.status}
                    </Badge>
                  </div>,
                  <div
                    key="id"
                    className="min-w-[280px]"
                  >
                    <span className="block font-medium text-gray-900">
                      {item.context_label || item.case_id}
                    </span>
                    <span className="mt-1 block font-mono text-[11px] text-gray-500">
                      {item.case_id}
                    </span>
                    {actionConfig && (
                      <div className="mt-3">
                        {renderActionButton({
                          icon: actionConfig.icon,
                          label: actionConfig.label,
                          loadingLabel: actionConfig.loadingLabel,
                          loading:
                            actionLoading === `${item.case_id}:${actionConfig.action}`,
                          onClick: () => runAction(item.case_id, actionConfig.action),
                          className: `${actionButtonClassName} ${actionConfig.className}`,
                        })}
                      </div>
                    )}
                  </div>,
                  <div key="emp" className="min-w-[190px]">
                    <span className="block max-w-[180px] truncate font-medium text-gray-900">
                      {item.employee?.name || item.employee_phone || "-"}
                    </span>
                    <span className="mt-1 block text-xs text-gray-500">
                      {item.employee_phone || item.phone || "Sin teléfono"}
                    </span>
                  </div>,
                  <span key="fondos" className="text-sm font-semibold text-gray-900">
                    {formatCLP(item.fondos_entregados)}
                  </span>,
                  <span key="aprobado" className="text-sm font-medium text-emerald-700">
                    {formatCLP(item.monto_rendido_aprobado)}
                  </span>,
                  <span
                    key="saldo"
                    className={`text-sm font-medium ${
                      (item.saldo_restante ?? 0) < 0
                        ? "text-red-600"
                        : "text-gray-900"
                    }`}
                  >
                    {formatCLP(item.saldo_restante)}
                  </span>,
                ];
              })}
            />
          )}
        </SectionCard>
      </Shell>
    </ProtectedPage>
  );
}
