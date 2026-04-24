"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import {
  CheckCircle,
  ClipboardCheck,
  ChevronDown,
  Clock,
  FileText,
  LoaderCircle,
  Lock,
  MessageSquare,
  Pencil,
  PlusCircle,
  Send,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import { ChatPanel } from "@/components/chat-panel";
import { DataTable } from "@/components/data-table";
import { Badge } from "@/components/badge";
import { ProtectedPage } from "@/components/protected-page";
import { SectionCard } from "@/components/section-card";
import { Shell } from "@/components/shell";
import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api";
import { useAutoRefresh } from "@/lib/use-auto-refresh";
import type { CaseItem, Conversation, Employee, Expense } from "@/lib/types";

const rendicionStatusLabels: Record<string, string> = {
  open: "Abierta",
  pending_user_confirmation: "Esperando confirmación del usuario",
  approved: "Aprobada",
  closed: "Cerrada",
};

const settlementDirectionLabels: Record<string, string> = {
  balanced: "Cuadrada",
  company_owes_employee: "Empresa debe reembolsar",
  employee_owes_company: "Trabajador debe devolver",
};

const settlementStatusLabels: Record<string, string> = {
  settlement_pending: "Liquidación pendiente",
  settled: "Liquidación resuelta",
};

const closureMethodLabels: Record<string, string> = {
  docusign: "DocuSign",
  simple: "Cierre Simple",
};

const employeeFieldLabels: Record<string, string> = {
  company_id: "Empresa",
  rut: "RUT",
  email: "Email",
  bank_name: "Banco",
  account_type: "Tipo de cuenta",
  account_number: "Número de cuenta",
  account_holder: "Titular",
  account_holder_rut: "RUT titular",
};

function formatCLP(value?: number | string): string {
  const num = typeof value === "string" ? parseFloat(value) : value;
  if (num == null || isNaN(num)) return "-";
  return `$${num.toLocaleString("es-CL", { maximumFractionDigits: 0 })}`;
}

function ReviewScoreBadge({ score }: { score?: number }) {
  if (score == null) return <span className="text-xs text-gray-400">-</span>;
  let color = "bg-red-100 text-red-700";
  if (score >= 80) color = "bg-emerald-100 text-emerald-700";
  else if (score >= 50) color = "bg-amber-100 text-amber-700";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-bold ${color}`}
    >
      {score}
    </span>
  );
}

type TimelineEvent = {
  date: string;
  label: string;
  detail?: string;
  icon: React.ElementType;
  tone: "default" | "success" | "warning" | "error";
};

function buildTimeline(
  item: CaseItem,
  expenses: Expense[],
): TimelineEvent[] {
  const events: TimelineEvent[] = [];

  if (item.created_at) {
    events.push({
      date: item.created_at,
      label: "Rendición creada",
      icon: PlusCircle,
      tone: "default",
    });
  }

  for (const exp of expenses) {
    if (exp.created_at) {
      events.push({
        date: exp.created_at,
        label: "Documento subido",
        detail: exp.merchant || exp.expense_id,
        icon: FileText,
        tone: "default",
      });
    }
    if (exp.review_status === "approved" && exp.updated_at) {
      events.push({
        date: exp.updated_at,
        label: "Documento aprobado",
        detail: exp.merchant || exp.expense_id,
        icon: CheckCircle,
        tone: "success",
      });
    }
    if (exp.review_status === "rejected" && exp.updated_at) {
      events.push({
        date: exp.updated_at,
        label: "Documento rechazado",
        detail: exp.merchant || exp.expense_id,
        icon: XCircle,
        tone: "error",
      });
    }
  }

  if (
    item.rendicion_status === "pending_user_confirmation" ||
    item.rendicion_status === "approved" ||
    item.rendicion_status === "closed"
  ) {
    const closureDetail =
      item.closure_method === "simple" ? "Confirmación WhatsApp" : "DocuSign";
    events.push({
      date: item.updated_at || item.created_at || "",
      label:
        item.closure_method === "simple"
          ? "Enviado a confirmación"
          : "Enviado a firma",
      detail: closureDetail,
      icon: Send,
      tone: "warning",
    });
  }

  if (item.user_confirmed_at) {
    events.push({
      date: item.user_confirmed_at,
      label:
        item.closure_method === "simple"
          ? "Confirmado por usuario"
          : "Firmado por usuario",
      icon: ShieldCheck,
      tone: "success",
    });
  }

  if (item.rendicion_status === "approved" && item.updated_at) {
    events.push({
      date: item.updated_at,
      label: "Rendición aprobada",
      icon: ClipboardCheck,
      tone: "success",
    });
  }

  if (item.rendicion_status === "closed" && item.updated_at) {
    events.push({
      date: item.updated_at,
      label: "Rendición cerrada",
      icon: Lock,
      tone: "default",
    });
  }

  events.sort((a, b) => a.date.localeCompare(b.date));
  return events;
}

const toneDot: Record<string, string> = {
  default: "bg-gray-400",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  error: "bg-red-500",
};

const toneIcon: Record<string, string> = {
  default: "text-gray-500",
  success: "text-emerald-600",
  warning: "text-amber-600",
  error: "text-red-600",
};

function formatDate(iso: string): string {
  if (!iso) return "";
  const d = iso.slice(0, 16).replace("T", " ");
  return d;
}

export default function CaseDetailPage() {
  const params = useParams<{ caseId: string }>();
  const { token } = useAuth();
  const caseId = typeof params.caseId === "string" ? params.caseId : "";
  const [item, setItem] = useState<CaseItem | null>(null);
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [saving, setSaving] = useState(false);
  const [isEditingBalanceMeta, setIsEditingBalanceMeta] = useState(false);
  const [actionLoading, setActionLoading] = useState("");
  const [actionError, setActionError] = useState("");
  const [closeRendicionPopupError, setCloseRendicionPopupError] = useState("");

  function fetchCase() {
    if (!token || !caseId) return;
    apiRequest<{
      case: CaseItem;
      employee: Employee;
      expenses: Expense[];
      conversations: Conversation[];
    }>(`/cases/${caseId}`, { token }).then((data) => {
      setActionError("");
      setItem(data.case);
      setEmployee(data.employee);
      setExpenses(data.expenses);
      setConversations(data.conversations);
    });
  }

  useEffect(() => {
    fetchCase();
  }, [caseId, token]);

  useAutoRefresh(
    () => fetchCase(),
    {
      enabled:
        Boolean(token) &&
        Boolean(caseId) &&
        !saving &&
        !isEditingBalanceMeta &&
        !actionLoading,
    },
  );

  async function onSubmitBalanceMeta(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !item) return;
    setSaving(true);
    try {
      const form = new FormData(event.currentTarget);
      const payload = Object.fromEntries(form.entries());
      await apiRequest(`/cases/${caseId}`, {
        method: "PUT",
        body: {
          ...item,
          ...payload,
          employee_phone: item.employee_phone || item.phone,
        },
        token,
      });
      setIsEditingBalanceMeta(false);
      fetchCase();
    } finally {
      setSaving(false);
    }
  }

  async function runAction(
    action:
      | "close"
      | "request_user_confirmation"
      | "resolve_settlement"
      | "close_rendicion",
  ) {
    if (!token) return;
    setActionLoading(action);
    setActionError("");
    if (action === "close_rendicion") {
      setCloseRendicionPopupError("");
    }
    try {
      await apiRequest(`/cases/${caseId}/actions`, {
        method: "POST",
        body: { action },
        token,
      });
      fetchCase();
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "No se pudo completar la acción sobre la rendición.";
      if (action === "close_rendicion") {
        setCloseRendicionPopupError(message);
      } else {
        setActionError(message);
      }
    } finally {
      setActionLoading("");
    }
  }

  const rendStatus = item?.rendicion_status || "open";
  const fondos =
    typeof item?.fondos_entregados === "string"
      ? parseFloat(item.fondos_entregados) || 0
      : item?.fondos_entregados || 0;
  const saldo = item?.saldo_restante ?? 0;
  const settlementDirection = item?.settlement_direction || "";
  const settlementStatus = item?.settlement_status || "";
  const settlementAmount = item?.settlement_amount_clp;
  const settlementNet = item?.settlement_net_clp;
  const showSettlementCard =
    rendStatus === "approved" ||
    rendStatus === "closed" ||
    Boolean(settlementStatus);

  return (
    <ProtectedPage>
      <Shell title="Detalle de rendición" description={caseId}>
        {closeRendicionPopupError && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/40 px-4">
            <div
              aria-modal="true"
              role="dialog"
              className="w-full max-w-md rounded-2xl border border-red-100 bg-white shadow-2xl"
            >
              <div className="flex items-start justify-between gap-4 border-b border-gray-100 px-5 py-4">
                <div>
                  <h2 className="text-base font-semibold text-gray-900">
                    No se pudo cerrar la rendición
                  </h2>
                  <p className="mt-1 text-sm text-gray-500">
                    Revisa la condición pendiente antes de intentar nuevamente.
                  </p>
                </div>
                <button
                  aria-label="Cerrar popup"
                  className="rounded-lg p-2 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700"
                  onClick={() => setCloseRendicionPopupError("")}
                  type="button"
                >
                  <XCircle className="h-5 w-5" />
                </button>
              </div>
              <div className="px-5 py-4">
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {closeRendicionPopupError}
                </div>
                <div className="mt-5 flex justify-end">
                  <button
                    className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700"
                    onClick={() => setCloseRendicionPopupError("")}
                    type="button"
                  >
                    Entendido
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {!item && (
          <div
            className="mb-6 flex items-center gap-2 rounded-xl border border-primary-100 bg-white px-5 py-4 text-sm font-medium text-gray-700 shadow-sm"
            role="status"
            aria-live="polite"
          >
            <LoaderCircle className="h-4 w-4 animate-spin text-primary-600" />
            Cargando rendición...
          </div>
        )}

        <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-12">
          <div className="space-y-6 xl:col-span-8">
            {item && (
              <section className="rounded-xl border border-gray-200 bg-white shadow-sm">
                <div className="flex flex-wrap items-start justify-between gap-3 border-b border-gray-100 px-5 py-4">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-3">
                      <h3 className="text-sm font-semibold text-gray-900">
                        Balance de rendición
                      </h3>
                      <Badge>
                        {rendicionStatusLabels[rendStatus] || rendStatus}
                      </Badge>
                      {["confirmed", "confirmed_simple"].includes(
                        item.user_confirmation_status || "",
                      ) && (
                        <span className="inline-flex items-center gap-1 text-xs text-emerald-600">
                          <CheckCircle className="h-3.5 w-3.5" />
                          {item.closure_method === "simple" ? "Confirmado" : "Firmado"}
                          {item.user_confirmed_at
                            ? ` el ${item.user_confirmed_at.slice(0, 10)}`
                            : ""}
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-gray-600">
                      <span className="inline-flex items-center rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1">
                        Empresa asociada: {item.company_id || "-"}
                      </span>
                      {item.closure_method === "docusign" && (
                        <span className="inline-flex items-center rounded-full border border-primary-200 bg-primary-50 px-2.5 py-1 text-primary-700">
                          Cierre: DocuSign
                        </span>
                      )}
                    </div>
                  </div>
                  <button
                    className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                    onClick={() => setIsEditingBalanceMeta((current) => !current)}
                    type="button"
                  >
                    <Pencil className="h-4 w-4" />
                    {isEditingBalanceMeta ? "Cancelar" : "Editar"}
                  </button>
                </div>

                <div className="space-y-4 p-5">
                  {isEditingBalanceMeta && (
                    <form
                      className="grid grid-cols-1 gap-4 rounded-xl border border-gray-200 bg-gray-50 p-4 lg:grid-cols-[minmax(0,1fr)_220px_140px]"
                      onSubmit={onSubmitBalanceMeta}
                    >
                      <div>
                        <label className="mb-1.5 block text-sm font-medium text-gray-700">
                          Empresa asociada
                        </label>
                        <input
                          defaultValue={item.company_id || ""}
                          name="company_id"
                          className="block w-full rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                        />
                      </div>
                      <div>
                        <label className="mb-1.5 block text-sm font-medium text-gray-700">
                          Método de cierre
                        </label>
                        <select
                          defaultValue={String(item.closure_method || "docusign")}
                          name="closure_method"
                          className="block w-full rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                        >
                          {Object.entries(closureMethodLabels).map(([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="flex items-end">
                        <button
                          className="w-full rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700 disabled:opacity-50"
                          type="submit"
                          disabled={saving}
                        >
                          {saving ? "Guardando..." : "Guardar"}
                        </button>
                      </div>
                    </form>
                  )}

                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-4">
                    <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
                      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-gray-500">
                        Fondos entregados
                      </p>
                      <p className="text-lg font-semibold text-gray-900">
                        {formatCLP(fondos)}
                      </p>
                    </div>
                    <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
                      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-emerald-600">
                        Rendido aprobado
                      </p>
                      <p className="text-lg font-semibold text-emerald-700">
                        {formatCLP(item.monto_rendido_aprobado)}
                      </p>
                    </div>
                    <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-amber-600">
                        Pendiente revisión
                      </p>
                      <p className="text-lg font-semibold text-amber-700">
                        {formatCLP(item.monto_pendiente_revision)}
                      </p>
                    </div>
                    <div
                      className={`rounded-xl border px-4 py-3 ${
                        saldo < 0
                          ? "border-red-200 bg-red-50"
                          : "border-gray-200 bg-gray-50"
                      }`}
                    >
                      <p
                        className={`mb-1 text-xs font-medium uppercase tracking-wide ${saldo < 0 ? "text-red-600" : "text-gray-500"}`}
                      >
                        Saldo restante
                      </p>
                      <p
                        className={`text-lg font-semibold ${saldo < 0 ? "text-red-700" : "text-gray-900"}`}
                      >
                        {formatCLP(saldo)}
                      </p>
                    </div>
                  </div>

                  {showSettlementCard && (settlementDirection || settlementStatus) && (
                    <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold text-gray-900">
                          Liquidación final
                        </span>
                        {settlementStatus && (
                          <Badge>
                            {settlementStatusLabels[settlementStatus] || settlementStatus}
                          </Badge>
                        )}
                      </div>
                      <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
                        <div>
                          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
                            Resultado
                          </p>
                          <p className="mt-1 text-sm font-medium text-gray-900">
                            {settlementDirectionLabels[settlementDirection] ||
                              settlementDirection ||
                              "-"}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
                            Monto liquidación
                          </p>
                          <p className="mt-1 text-sm font-medium text-gray-900">
                            {formatCLP(settlementAmount)}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
                            Neto
                          </p>
                          <p className="mt-1 text-sm font-medium text-gray-900">
                            {formatCLP(settlementNet)}
                          </p>
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="flex flex-wrap items-center gap-2">
                    {rendStatus === "open" && (
                      <button
                        className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3.5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700 disabled:opacity-50"
                        onClick={() => runAction("request_user_confirmation")}
                        disabled={actionLoading === "request_user_confirmation"}
                        type="button"
                      >
                        <Send className="h-4 w-4" />
                        {actionLoading === "request_user_confirmation"
                          ? "Enviando..."
                          : item.closure_method === "simple"
                            ? "Solicitar confirmación al usuario"
                            : "Solicitar firma al usuario"}
                      </button>
                    )}
                    {rendStatus === "pending_user_confirmation" && (
                      <span className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-3.5 py-2 text-sm font-medium text-amber-700">
                        <FileText className="h-4 w-4" />
                        {item.closure_method === "simple"
                          ? "Esperando confirmación del usuario por WhatsApp"
                          : "Esperando firma del usuario via DocuSign"}
                      </span>
                    )}
                    {rendStatus === "approved" && (
                      <>
                        {settlementStatus === "settlement_pending" && (
                          <button
                            className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 px-3.5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-sky-700 disabled:opacity-50"
                            onClick={() => runAction("resolve_settlement")}
                            disabled={actionLoading === "resolve_settlement"}
                            type="button"
                          >
                            <ClipboardCheck className="h-4 w-4" />
                            {actionLoading === "resolve_settlement"
                              ? "Registrando..."
                              : "Marcar liquidación resuelta"}
                          </button>
                        )}
                        <button
                          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3.5 py-2 text-sm font-semibold text-gray-700 transition hover:bg-gray-50 disabled:opacity-50"
                          onClick={() => runAction("close_rendicion")}
                          disabled={actionLoading === "close_rendicion"}
                          type="button"
                        >
                          <Lock className="h-4 w-4" />
                          {actionLoading === "close_rendicion"
                            ? "Cerrando..."
                            : "Cerrar rendición"}
                        </button>
                      </>
                    )}
                  </div>
                  {actionError && (
                    <div className="rounded-lg border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-700">
                      {actionError}
                    </div>
                  )}
                </div>
              </section>
            )}

            <SectionCard title="Documentos de la rendición">
              <DataTable
                columns={[
                  "Score",
                  "Merchant",
                  "Fecha",
                  "Monto",
                  "Review",
                  "Estado",
                  "",
                ]}
                rows={expenses.map((expense) => [
                  <ReviewScoreBadge
                    key="score"
                    score={expense.review_score}
                  />,
                  <span key="merchant" className="text-sm">
                    {expense.merchant || "-"}
                  </span>,
                  <span key="date" className="text-xs text-gray-500">
                    {expense.date || "-"}
                  </span>,
                  <span key="amount" className="text-sm font-medium">
                    {`${expense.currency || ""} ${expense.total || "-"}`}
                  </span>,
                  <Badge key="review">
                    {expense.review_status || "-"}
                  </Badge>,
                  <Badge key="status">{expense.status || "-"}</Badge>,
                  <Link
                    key="link"
                    className="text-sm font-medium text-primary-600 transition hover:text-primary-700"
                    href={`/expenses/${expense.expense_id}`}
                  >
                    Ver
                  </Link>,
                ])}
              />
            </SectionCard>
          </div>

          <div className="space-y-6 xl:col-span-4">
            <SectionCard title="Persona asociada">
              {employee ? (
                <div className="space-y-3">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-100 text-sm font-semibold text-primary-700">
                      {employee.name?.charAt(0)?.toUpperCase() || "?"}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-gray-900">
                        {employee.name}
                      </p>
                      <p className="font-mono text-xs text-gray-500">
                        {employee.phone}
                      </p>
                    </div>
                  </div>
                  <details className="group rounded-xl border border-gray-200 bg-gray-50">
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-medium text-gray-900">
                      <span>Ver más información</span>
                      <ChevronDown className="h-4 w-4 text-gray-500 transition group-open:rotate-180" />
                    </summary>
                    <div className="grid grid-cols-1 gap-3 border-t border-gray-200 bg-white p-4">
                      {(
                        [
                          "company_id",
                          "rut",
                          "email",
                          "bank_name",
                          "account_type",
                          "account_number",
                          "account_holder",
                          "account_holder_rut",
                        ] as const
                      ).map((field) => (
                        <div key={field} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                          <p className="text-[11px] font-medium uppercase tracking-wide text-gray-500">
                            {employeeFieldLabels[field]}
                          </p>
                          <p className="mt-1 text-sm text-gray-900">
                            {employee[field] || "-"}
                          </p>
                        </div>
                      ))}
                    </div>
                  </details>
                  <Link
                    className="inline-flex items-center rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                    href={`/employees/${encodeURIComponent(employee.phone)}`}
                  >
                    Ver persona
                  </Link>
                </div>
              ) : (
                <p className="text-sm text-gray-500">
                  Sin persona vinculada.
                </p>
              )}
            </SectionCard>

            {item && (
              <SectionCard title="Historial de actividad">
                {(() => {
                  const events = buildTimeline(item, expenses);
                  if (events.length === 0)
                    return (
                      <p className="text-sm text-gray-500">
                        Sin actividad registrada.
                      </p>
                    );
                  return (
                    <div className="relative space-y-0">
                      {events.map((event, i) => {
                        const Icon = event.icon;
                        return (
                          <div key={i} className="relative flex gap-3 pb-5 last:pb-0">
                            {i < events.length - 1 && (
                              <div className="absolute left-[11px] top-6 h-full w-px bg-gray-200" />
                            )}
                            <div
                              className={`relative z-10 mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-white ring-2 ring-gray-100`}
                            >
                              <Icon
                                className={`h-3.5 w-3.5 ${toneIcon[event.tone]}`}
                              />
                            </div>
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-gray-900">
                                {event.label}
                              </p>
                              {event.detail && (
                                <p className="truncate text-xs text-gray-500">
                                  {event.detail}
                                </p>
                              )}
                              <p className="mt-0.5 text-xs text-gray-400">
                                {formatDate(event.date)}
                              </p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  );
                })()}
              </SectionCard>
            )}

            {(item?.employee_phone || item?.phone) && (
              <ChatPanel
                phone={item.employee_phone || item.phone || ""}
                maxHeight="400px"
              />
            )}
          </div>
        </div>
      </Shell>
    </ProtectedPage>
  );
}
