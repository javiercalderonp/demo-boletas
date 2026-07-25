"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Building2,
  ChevronDown,
  ChevronRight,
  CircleDollarSign,
  FileText,
  Mail,
  Pencil,
  Receipt,
  UserRound,
  X,
} from "lucide-react";

import { Badge } from "@/components/badge";
import { ProtectedPage } from "@/components/protected-page";
import { SectionCard } from "@/components/section-card";
import { Shell } from "@/components/shell";
import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api";
import { useAutoRefresh } from "@/lib/use-auto-refresh";
import type { CaseItem, Company, Conversation, Employee, Expense } from "@/lib/types";

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

const statusLabels: Record<string, string> = {
  active: "Activo",
  closed: "Cerrado",
  inactive: "Inactivo",
  approved: "Aprobado",
  rejected: "Rechazado",
  pending: "Pendiente",
  pending_review: "Pendiente de revisión",
  ready_to_approve: "Listo para aprobar",
  needs_manual_review: "Revisión manual",
  observed: "Observado",
  open: "Abierta",
  in_progress: "En curso",
  pending_user_confirmation: "Esperando confirmación",
  WAIT_RECEIPT: "Esperando comprobante",
  PROCESSING: "Procesando",
  NEEDS_INFO: "Falta información",
  CONFIRM_SUMMARY: "Esperando confirmación",
  DONE: "Finalizado",
};

function statusLabel(value?: string) {
  if (!value) return "Sin estado";
  return statusLabels[value] || statusLabels[value.toLowerCase()] || value.replaceAll("_", " ");
}

function toNumber(value?: number | string) {
  const parsed = typeof value === "number" ? value : Number(String(value || "").replace(",", "."));
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatClp(value?: number | string) {
  return new Intl.NumberFormat("es-CL", {
    style: "currency",
    currency: "CLP",
    maximumFractionDigits: 0,
  }).format(toNumber(value));
}

function formatDate(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es-CL", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

function caseTitle(item: CaseItem) {
  if (item.context_label?.trim()) return item.context_label.trim();
  const date = item.created_at ? new Date(item.created_at) : null;
  if (date && !Number.isNaN(date.getTime())) {
    const month = new Intl.DateTimeFormat("es-CL", { month: "long", year: "numeric" }).format(date);
    return `Rendición de ${month}`;
  }
  return item.status === "active" ? "Rendición activa" : "Rendición";
}

function conversationMessage(conversation?: Conversation) {
  if (!conversation) return "";
  const messages: Record<string, string> = {
    WAIT_RECEIPT: "Esperando que el usuario envíe un nuevo comprobante.",
    PROCESSING: "El comprobante enviado por el usuario está siendo procesado.",
    NEEDS_INFO: "Falta información del usuario para continuar.",
    CONFIRM_SUMMARY: "Esperando que el usuario confirme el resumen de su rendición.",
    DONE: "La conversación asociada a esta rendición finalizó.",
  };
  return messages[conversation.state] || `Conversación: ${statusLabel(conversation.state)}.`;
}

function ReceiptPreview({ expense }: { expense: Expense }) {
  const [failed, setFailed] = useState(false);
  const imageUrl = expense.image_url?.trim();

  if (!imageUrl || failed) {
    return (
      <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-xl border border-gray-200 bg-gray-50 text-gray-400">
        <FileText className="h-6 w-6" aria-hidden="true" />
        <span className="sr-only">Comprobante sin vista previa</span>
      </div>
    );
  }

  return (
    <img
      src={imageUrl}
      alt={`Comprobante de ${expense.merchant || "gasto"}`}
      className="h-16 w-16 shrink-0 rounded-xl border border-gray-200 object-cover"
      onError={() => setFailed(true)}
    />
  );
}

function Metric({
  label,
  value,
  emphasis,
}: {
  label: string;
  value: React.ReactNode;
  emphasis?: boolean;
}) {
  return (
    <div className="min-w-0 rounded-xl bg-gray-50 px-4 py-3">
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <p className={`mt-1 truncate font-semibold ${emphasis ? "text-lg text-gray-950" : "text-sm text-gray-900"}`}>
        {value}
      </p>
    </div>
  );
}

export default function EmployeeDetailPage() {
  const params = useParams<{ phone: string }>();
  const { token } = useAuth();
  const phone = typeof params.phone === "string" ? decodeURIComponent(params.phone) : "";
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [saving, setSaving] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [error, setError] = useState("");

  function fetchEmployeeDetail() {
    if (!token || !phone) return;
    return Promise.all([
      apiRequest<{
        employee: Employee;
        cases: CaseItem[];
        expenses: Expense[];
        conversations: Conversation[];
      }>(`/employees/${encodeURIComponent(phone)}`, { token }),
      apiRequest<{ items: Company[] }>("/companies", { token }),
    ])
      .then(([data, companiesData]) => {
        const sortedCases = [...data.cases].sort((a, b) => {
          if (a.status === "active" && b.status !== "active") return -1;
          if (b.status === "active" && a.status !== "active") return 1;
          return String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || ""));
        });
        setEmployee(data.employee);
        setCases(sortedCases);
        setExpenses(data.expenses);
        setConversations(data.conversations);
        setCompanies(companiesData.items.filter((company) => company.active));
        setSelectedCaseId((current) =>
          current && sortedCases.some((item) => item.case_id === current)
            ? current
            : sortedCases[0]?.case_id || "",
        );
        setError("");
      })
      .catch((nextError) => {
        setError(nextError instanceof Error ? nextError.message : "No se pudo cargar la persona.");
      });
  }

  useEffect(() => {
    void fetchEmployeeDetail();
  }, [phone, token]);

  useAutoRefresh(() => fetchEmployeeDetail(), {
    enabled: Boolean(token) && Boolean(phone) && !saving && !editOpen,
  });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !employee) return;
    setSaving(true);
    setError("");
    try {
      const form = new FormData(event.currentTarget);
      const payload = Object.fromEntries(form.entries());
      await apiRequest(`/employees/${encodeURIComponent(phone)}`, {
        method: "PUT",
        body: { ...employee, ...payload, active: employee.active },
        token,
      });
      await fetchEmployeeDetail();
      setEditOpen(false);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "No se pudieron guardar los cambios.");
    } finally {
      setSaving(false);
    }
  }

  const companyById = useMemo(
    () => new Map(companies.map((company) => [company.company_id, company.name])),
    [companies],
  );
  const selectedCase = cases.find((item) => item.case_id === selectedCaseId) || cases[0];
  const selectedExpenses = selectedCase
    ? expenses.filter((expense) => expense.case_id === selectedCase.case_id)
    : expenses;
  const selectedConversation = selectedCase
    ? conversations.find((item) => item.case_id === selectedCase.case_id)
    : conversations[0];
  const totalSpent = selectedExpenses.reduce(
    (sum, item) => sum + toNumber(item.total_clp ?? item.total),
    0,
  );
  const totalAllExpenses = expenses.reduce(
    (sum, item) => sum + toNumber(item.total_clp ?? item.total),
    0,
  );
  const budget = toNumber(selectedCase?.fondos_entregados);
  const approvedCount = selectedExpenses.filter((item) => item.status === "approved").length;
  const rejectedCount = selectedExpenses.filter((item) => item.status === "rejected").length;
  const availableBalance = selectedCase?.saldo_restante !== undefined
    ? toNumber(selectedCase.saldo_restante)
    : budget - totalSpent;
  const activeCases = cases.filter((item) => item.status === "active").length;
  const personName = employee
    ? [employee.first_name, employee.last_name].filter(Boolean).join(" ") || employee.name || "Persona"
    : "Persona";
  const initials = personName
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");

  return (
    <ProtectedPage>
      <Shell title="Detalle de persona" description={personName}>
        {error && (
          <div className="mb-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
            {error}
          </div>
        )}

        {!employee ? (
          <div className="space-y-6">
            <div className="skeleton h-48 w-full rounded-xl" />
            <div className="skeleton h-72 w-full rounded-xl" />
            <div className="skeleton h-80 w-full rounded-xl" />
          </div>
        ) : (
          <div className="space-y-6">
            <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
              <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
                <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-primary-100 text-xl font-bold text-primary-700">
                  {initials || <UserRound className="h-7 w-7" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <h2 className="text-2xl font-semibold tracking-tight text-gray-950">{personName}</h2>
                      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2 text-sm text-gray-600">
                        <span className="inline-flex items-center gap-1.5">
                          <Mail className="h-4 w-4 text-gray-400" /> {employee.email || "Sin email"}
                        </span>
                        <span>RUT {employee.rut || "no informado"}</span>
                        <span className="inline-flex items-center gap-1.5">
                          <Building2 className="h-4 w-4 text-gray-400" />
                          {companyById.get(employee.company_id || "") || employee.company_id || "Sin empresa"}
                        </span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setEditOpen(true)}
                      className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-semibold text-gray-700 shadow-sm transition hover:bg-gray-50"
                    >
                      <Pencil className="h-4 w-4" /> Editar persona
                    </button>
                  </div>
                  <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3">
                    <Metric label="Casos activos" value={activeCases} />
                    <Metric label="Gastos totales" value={expenses.length} />
                    <Metric label="Última actividad" value={formatDate(employee.last_activity_at) || "Sin registro"} />
                  </div>
                </div>
              </div>
            </section>

            <SectionCard
              title="Caso asociado"
              action={
                cases.length > 1 ? (
                  <label className="relative">
                    <span className="sr-only">Seleccionar caso</span>
                    <select
                      value={selectedCase?.case_id || ""}
                      onChange={(event) => setSelectedCaseId(event.target.value)}
                      className="appearance-none rounded-lg border border-gray-200 bg-white py-1.5 pl-3 pr-8 text-sm font-medium text-gray-700 outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
                    >
                      {cases.map((item) => (
                        <option key={item.case_id} value={item.case_id}>{caseTitle(item)}</option>
                      ))}
                    </select>
                    <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                  </label>
                ) : undefined
              }
            >
              {selectedCase ? (
                <div>
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-xl font-semibold text-gray-950">{caseTitle(selectedCase)}</h3>
                        <Badge tone={selectedCase.status}>{statusLabel(selectedCase.status)}</Badge>
                      </div>
                      <p className="mt-1 text-sm text-gray-500">
                        {companyById.get(selectedCase.company_id || "") || selectedCase.company_id || "Empresa no informada"}
                        {selectedCase.updated_at && ` · Actualizado ${formatDate(selectedCase.updated_at)}`}
                      </p>
                      <p className="mt-1 font-mono text-[11px] text-gray-400" title="Identificador técnico del caso">
                        ID {selectedCase.case_id}
                      </p>
                    </div>
                    <Link
                      href={`/cases/${selectedCase.case_id}`}
                      className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg bg-primary-600 px-3.5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700"
                    >
                      Ver detalle <ChevronRight className="h-4 w-4" />
                    </Link>
                  </div>

                  <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
                    <Metric label="Total gastado" value={formatClp(totalSpent)} emphasis />
                    <Metric label="Fondos entregados" value={formatClp(budget)} />
                    <Metric label="Saldo disponible" value={formatClp(availableBalance)} />
                    <Metric label="Estado rendición" value={statusLabel(selectedCase.rendicion_status || selectedCase.status)} />
                    <Metric label="Total de gastos" value={selectedExpenses.length} />
                    <Metric label="Aprobados" value={approvedCount} />
                    <Metric label="Rechazados" value={rejectedCount} />
                    <Metric
                      label="Liquidación"
                      value={
                        selectedCase.settlement_amount_clp
                          ? formatClp(selectedCase.settlement_amount_clp)
                          : statusLabel(selectedCase.settlement_status)
                      }
                    />
                  </div>

                  {budget > 0 && (
                    <div className="mt-5">
                      <div className="mb-2 flex items-center justify-between text-xs font-medium text-gray-500">
                        <span>Uso de fondos</span>
                        <span>{Math.round((totalSpent / budget) * 100)}%</span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-gray-100">
                        <div
                          className="h-full rounded-full bg-primary-500 transition-all"
                          style={{ width: `${Math.min((totalSpent / budget) * 100, 100)}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {selectedConversation && (
                    <p className="mt-5 rounded-lg border border-blue-100 bg-blue-50 px-3.5 py-3 text-sm text-blue-800">
                      {conversationMessage(selectedConversation)}
                    </p>
                  )}
                </div>
              ) : (
                <div className="py-8 text-center">
                  <CircleDollarSign className="mx-auto h-8 w-8 text-gray-300" />
                  <p className="mt-2 text-sm font-medium text-gray-700">Esta persona aún no tiene casos asociados.</p>
                </div>
              )}
            </SectionCard>

            <SectionCard
              title={
                <span className="inline-flex flex-wrap items-center gap-2">
                  Gastos asociados
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
                    {expenses.length}
                  </span>
                </span>
              }
              action={<span className="text-sm font-semibold text-gray-900">{formatClp(totalAllExpenses)}</span>}
            >
              {expenses.length ? (
                <div className="divide-y divide-gray-100">
                  {expenses.map((expense) => {
                    const observation = expense.review_reason || expense.primary_review_reason;
                    return (
                      <Link
                        key={expense.expense_id}
                        href={`/expenses/${expense.expense_id}`}
                        className="-mx-3 flex items-center gap-3 rounded-xl px-3 py-4 transition hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-primary-200 sm:gap-4"
                        aria-label={`Ver gasto de ${expense.merchant || "comercio no informado"} por ${formatClp(expense.total_clp ?? expense.total)}`}
                      >
                        <ReceiptPreview expense={expense} />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
                            <div className="min-w-0">
                              <p className="truncate font-semibold text-gray-950">{expense.merchant || "Comercio no informado"}</p>
                              <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-gray-500">
                                <span>{expense.category || expense.document_type || "Documento sin categoría"}</span>
                                {expense.date && <span>· {formatDate(expense.date)}</span>}
                              </p>
                            </div>
                            <p className="shrink-0 text-base font-semibold text-gray-950">
                              {formatClp(expense.total_clp ?? expense.total)}
                            </p>
                          </div>
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            <Badge tone={expense.status}>{statusLabel(expense.status)}</Badge>
                            {observation && (
                              <span className="line-clamp-1 text-xs text-red-600">{observation}</span>
                            )}
                            <span className="font-mono text-[10px] text-gray-400">ID {expense.expense_id}</span>
                          </div>
                        </div>
                        <ChevronRight className="h-5 w-5 shrink-0 text-gray-300" aria-hidden="true" />
                      </Link>
                    );
                  })}
                </div>
              ) : (
                <div className="py-10 text-center">
                  <Receipt className="mx-auto h-8 w-8 text-gray-300" />
                  <p className="mt-2 text-sm font-medium text-gray-700">No hay gastos asociados.</p>
                </div>
              )}
            </SectionCard>
          </div>
        )}

        {editOpen && employee && (
          <div className="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/40 p-0 sm:items-center sm:p-4">
            <button
              type="button"
              className="absolute inset-0 cursor-default"
              aria-label="Cerrar edición"
              onClick={() => !saving && setEditOpen(false)}
            />
            <div
              role="dialog"
              aria-modal="true"
              aria-labelledby="edit-person-title"
              className="relative max-h-[92dvh] w-full overflow-y-auto rounded-t-2xl bg-white shadow-xl sm:max-w-2xl sm:rounded-2xl"
            >
              <div className="sticky top-0 z-10 flex items-center justify-between border-b border-gray-100 bg-white px-5 py-4">
                <div>
                  <h2 id="edit-person-title" className="text-lg font-semibold text-gray-950">Editar persona</h2>
                  <p className="text-sm text-gray-500">Actualiza sus datos personales y bancarios.</p>
                </div>
                <button
                  type="button"
                  onClick={() => setEditOpen(false)}
                  disabled={saving}
                  className="rounded-lg p-2 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700 disabled:opacity-50"
                  aria-label="Cerrar"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <form
                key={JSON.stringify(employee)}
                className="p-5"
                onSubmit={onSubmit}
              >
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="sm:col-span-2">
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Empresa</label>
                    <select name="company_id" defaultValue={employee.company_id || ""} className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100">
                      <option value="">Selecciona una empresa</option>
                      {companies.map((company) => <option key={company.company_id} value={company.company_id}>{company.name}</option>)}
                    </select>
                  </div>
                  {(["rut", "first_name", "last_name", "email"] as const).map((field) => (
                    <div key={field} className={field === "email" ? "sm:col-span-2" : ""}>
                      <label className="mb-1.5 block text-sm font-medium text-gray-700">{fieldLabels[field]}</label>
                      <input
                        defaultValue={employee[field] || ""}
                        name={field}
                        type={field === "email" ? "email" : "text"}
                        className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                      />
                    </div>
                  ))}
                </div>

                <div className="my-5 border-t border-gray-100" />
                <div className="mb-3 flex items-center gap-2">
                  <Building2 className="h-4 w-4 text-gray-400" />
                  <h3 className="text-sm font-semibold text-gray-900">Datos bancarios opcionales</h3>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  {(["bank_name", "account_type", "account_number", "account_holder", "account_holder_rut"] as const).map((field) => (
                    <div key={field}>
                      <label className="mb-1.5 block text-sm font-medium text-gray-700">{fieldLabels[field]}</label>
                      <input
                        defaultValue={employee[field] || ""}
                        name={field}
                        className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                      />
                    </div>
                  ))}
                </div>
                <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
                  <button type="button" onClick={() => setEditOpen(false)} disabled={saving} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 transition hover:bg-gray-50 disabled:opacity-50">
                    Cancelar
                  </button>
                  <button type="submit" disabled={saving} className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700 disabled:opacity-50">
                    {saving ? "Guardando..." : "Guardar cambios"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </Shell>
    </ProtectedPage>
  );
}
