"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, CircleDollarSign,
  Clock3, Download, Eye, FileImage, FileText, FolderOpen, Landmark, LoaderCircle,
  Lock, MessageCircle, Pencil, Receipt, Send, UserRound, WalletCards, XCircle,
} from "lucide-react";

import { Badge } from "@/components/badge";
import { ChatPanel } from "@/components/chat-panel";
import { ProtectedPage } from "@/components/protected-page";
import { RejectExpenseDialog } from "@/components/reject-expense-dialog";
import { Shell } from "@/components/shell";
import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api";
import { useAutoRefresh } from "@/lib/use-auto-refresh";
import type { CaseItem, Employee, Expense } from "@/lib/types";

const STATUS_LABELS: Record<string, string> = {
  active: "Activa", open: "Abierta", approved: "Aprobada", rejected: "Rechazada",
  pending: "Pendiente", closed: "Cerrada",
  pending_user_confirmation: "Esperando confirmación",
  settlement_pending: "Liquidación pendiente",
  pending_company_payment: "Pendiente de pago de la empresa",
  pending_employee_payment: "Pendiente de devolución de la persona",
  settled: "Liquidación completada",
  WAIT_RECEIPT: "Esperando comprobante", PROCESSING: "Procesando documento",
  NEEDS_INFO: "Esperando información adicional",
  CONFIRM_SUMMARY: "Esperando confirmación", DONE: "Caso finalizado",
};

const DIRECTION_LABELS: Record<string, string> = {
  balanced: "Sin saldo pendiente",
  company_owes_employee: "Empresa debe reembolsar",
  employee_owes_company: "Persona debe devolver",
};

const CLOSURE_LABELS: Record<string, string> = {
  docusign: "DocuSign",
  simple: "Cierre simple",
};

function humanizeStatus(value?: string): string {
  if (!value) return "Sin estado informado";
  return STATUS_LABELS[value] ?? STATUS_LABELS[value.toUpperCase()] ??
    value.replace(/_/g, " ").toLowerCase().replace(/^\w/, (letter) => letter.toUpperCase());
}

function formatClp(value?: number | string): string {
  const amount = parseAmount(value);
  return `$${Math.round(amount).toLocaleString("es-CL")}`;
}

function parseAmount(value?: number | string): number {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  if (!value) return 0;
  const amount = Number(value.replace(/\./g, "").replace(",", "."));
  return Number.isFinite(amount) ? amount : 0;
}

function expenseAmount(expense: Expense): number {
  const converted = parseAmount(expense.total_clp);
  return converted || (expense.currency === "CLP" ? parseAmount(expense.total) : 0);
}

function formatDate(value?: string, withTime = false): string {
  if (!value) return "Sin fecha";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es-CL", withTime
    ? { dateStyle: "medium", timeStyle: "short" }
    : { day: "numeric", month: "short", year: "numeric" }).format(date);
}

function documentLabel(type?: string): string {
  return type === "invoice" ? "Factura" :
    type === "professional_fee_receipt" ? "Boleta de honorarios" : "Boleta";
}

function MetricCard({
  label, value, detail, icon: Icon, tone = "neutral",
}: {
  label: string; value: string; detail?: string; icon: typeof WalletCards;
  tone?: "neutral" | "success" | "danger";
}) {
  const toneClass = tone === "danger" ? "text-red-700 bg-red-50" :
    tone === "success" ? "text-emerald-700 bg-emerald-50" : "text-slate-700 bg-slate-50";
  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-slate-500">{label}</p>
          <p className={`mt-1 truncate text-xl font-bold tabular-nums ${toneClass.split(" ")[0]}`}>{value}</p>
          {detail && <p className="mt-1 text-xs leading-4 text-slate-500">{detail}</p>}
        </div>
        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${toneClass}`}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
    </article>
  );
}

function ReceiptPreview({ expense }: { expense: Expense }) {
  const name = expense.merchant || "comercio no identificado";
  const [imageFailed, setImageFailed] = useState(false);
  if (expense.image_url && !imageFailed) {
    return (
      <img
        src={expense.image_url}
        alt={`Comprobante de ${name}`}
        className="h-16 w-16 rounded-xl border border-slate-200 object-cover"
        loading="lazy"
        onError={() => setImageFailed(true)}
      />
    );
  }
  return (
    <span className="flex h-16 w-16 shrink-0 flex-col items-center justify-center rounded-xl border border-slate-200 bg-slate-50 text-slate-400">
      {expense.document_url ? <FileText className="h-5 w-5 text-red-500" /> : <FileImage className="h-5 w-5" />}
      <span className="mt-1 text-[9px] font-semibold">{expense.document_url ? "PDF" : "SIN ARCHIVO"}</span>
    </span>
  );
}

function ExpenseRow({
  expense, selected, loading, showCenter, onSelect, onApprove, onReject,
}: {
  expense: Expense; selected: boolean; loading: string; showCenter?: boolean;
  onSelect: () => void; onApprove: () => void; onReject: () => void;
}) {
  const approved = expense.review_status === "approved";
  const rejected = expense.review_status === "rejected";
  const pending = !approved && !rejected;
  const approving = loading === `${expense.expense_id}:approve`;
  const rejecting = loading === `${expense.expense_id}:reject`;
  const status = approved ? "Aprobado" : rejected ? "Rechazado" : "Pendiente";

  return (
    <article className={`group grid gap-4 border-b border-slate-100 p-4 last:border-b-0 md:grid-cols-[auto_1fr_auto] md:items-center ${selected ? "bg-primary-50/40" : "bg-white hover:bg-slate-50/70"}`}>
      <div className="flex items-start gap-3">
        {pending && (
          <input
            aria-label={`Seleccionar gasto de ${expense.merchant || "comercio no identificado"}`}
            className="mt-5 h-4 w-4 rounded border-slate-300 accent-primary-600"
            type="checkbox"
            checked={selected}
            onChange={onSelect}
          />
        )}
        <Link href={`/expenses/${expense.expense_id}`} className="rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500">
          <ReceiptPreview expense={expense} />
        </Link>
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Link className="truncate font-semibold text-slate-900 hover:text-primary-700 focus:outline-none focus:underline" href={`/expenses/${expense.expense_id}`}>
            {expense.merchant || "Documento sin identificar"}
          </Link>
          <Badge tone={expense.review_status || "pending"}>{status}</Badge>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
          <span>{formatDate(expense.date)}</span>
          <span>{expense.category || "Sin categoría"}</span>
          <span>{documentLabel(expense.document_type)}</span>
          {showCenter && <span>{expense.cost_center || "Sin centro de costo"}</span>}
        </div>
        {rejected && expense.review_reason && (
          <p className="mt-2 text-xs text-red-600">Motivo: {expense.review_reason}</p>
        )}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 md:justify-end">
        <div className="text-left md:text-right">
          <p className="font-bold tabular-nums text-slate-900">{formatClp(expenseAmount(expense))}</p>
          <p className="text-xs text-slate-500">
            {expense.review_score == null ? "Sin score" : `${expense.review_score}% confianza`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link className="inline-flex h-9 items-center gap-1 rounded-lg border border-slate-300 px-3 text-xs font-semibold text-slate-700 hover:bg-white focus:outline-none focus:ring-2 focus:ring-primary-500" href={`/expenses/${expense.expense_id}`}>
            <Eye className="h-3.5 w-3.5" /> Ver
          </Link>
          {pending && (
            <>
              <button className="inline-flex h-9 items-center gap-1 rounded-lg bg-emerald-600 px-3 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50" disabled={Boolean(loading)} onClick={onApprove} type="button">
                <CheckCircle2 className="h-3.5 w-3.5" /> {approving ? "Aprobando…" : "Aprobar"}
              </button>
              <button className="inline-flex h-9 items-center gap-1 rounded-lg border border-red-200 px-3 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50" disabled={Boolean(loading)} onClick={onReject} type="button">
                <XCircle className="h-3.5 w-3.5" /> {rejecting ? "Rechazando…" : "Rechazar"}
              </button>
            </>
          )}
        </div>
      </div>
    </article>
  );
}

type TimelineEvent = { date: string; label: string; detail?: string; tone: "default" | "success" | "danger" };

function timelineFor(item: CaseItem, expenses: Expense[]): TimelineEvent[] {
  const events: TimelineEvent[] = [];
  if (item.created_at) events.push({ date: item.created_at, label: "Rendición creada", tone: "default" });
  expenses.forEach((expense) => {
    if (expense.created_at) events.push({ date: expense.created_at, label: "Gasto creado", detail: expense.merchant, tone: "default" });
    if (expense.review_status === "approved" && expense.updated_at) events.push({ date: expense.updated_at, label: "Gasto aprobado", detail: expense.merchant, tone: "success" });
    if (expense.review_status === "rejected" && expense.updated_at) events.push({ date: expense.updated_at, label: "Gasto rechazado", detail: expense.merchant, tone: "danger" });
  });
  if (item.user_confirmed_at) events.push({ date: item.user_confirmed_at, label: "Confirmado por la persona", tone: "success" });
  if (item.rendicion_status === "approved" && item.updated_at) events.push({ date: item.updated_at, label: "Rendición aprobada", tone: "success" });
  if (item.rendicion_status === "closed" && item.updated_at) events.push({ date: item.updated_at, label: "Rendición cerrada", tone: "default" });
  return events.sort((a, b) => b.date.localeCompare(a.date));
}

export default function CaseDetailPage() {
  const params = useParams<{ caseId: string }>();
  const caseId = typeof params.caseId === "string" ? params.caseId : "";
  const { token } = useAuth();
  const [item, setItem] = useState<CaseItem | null>(null);
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [conversationState, setConversationState] = useState("");
  const [activeTab, setActiveTab] = useState<"centers" | "all">("centers");
  const [expandedCenters, setExpandedCenters] = useState<Record<string, boolean>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [actionLoading, setActionLoading] = useState("");
  const [expenseLoading, setExpenseLoading] = useState("");
  const [documentLoading, setDocumentLoading] = useState(false);
  const [error, setError] = useState("");
  const [rejectIds, setRejectIds] = useState<string[] | null>(null);
  const [showAllActivity, setShowAllActivity] = useState(false);

  const fetchCase = useCallback(() => {
    if (!token || !caseId) return;
    apiRequest<{ case: CaseItem; employee: Employee; expenses: Expense[]; conversations: { state?: string }[] }>(`/cases/${caseId}`, { token })
      .then((data) => {
        setItem(data.case); setEmployee(data.employee); setExpenses(data.expenses);
        setConversationState(data.conversations?.[0]?.state || "");
        setError("");
      })
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "No se pudo cargar la rendición."));
  }, [caseId, token]);

  useEffect(() => { fetchCase(); }, [fetchCase]);
  useAutoRefresh(fetchCase, { enabled: Boolean(token && caseId && !editing && !actionLoading && !expenseLoading), intervalMs: 10000 });

  const budget = parseAmount(item?.fondos_entregados);
  const spent = useMemo(() => expenses.reduce((sum, expense) => sum + expenseAmount(expense), 0), [expenses]);
  const difference = budget > 0 ? spent - budget : null;
  const percent = budget > 0 ? Math.round((spent / budget) * 100) : null;
  const status = item?.rendicion_status || item?.status || "open";
  const timeline = useMemo(() => item ? timelineFor(item, expenses) : [], [item, expenses]);

  const centers = useMemo(() => {
    const names = new Set<string>([
      ...(item?.cost_centers || []),
      ...Object.keys(item?.fondos_por_centro || {}),
      ...expenses.map((expense) => expense.cost_center || "Sin centro de costo"),
    ].filter(Boolean));
    return Array.from(names).map((name) => {
      const centerExpenses = expenses.filter((expense) => (expense.cost_center || "Sin centro de costo") === name);
      const assignedValue = item?.fondos_por_centro?.[name];
      const assigned = parseAmount(assignedValue);
      const total = centerExpenses.reduce((sum, expense) => sum + expenseAmount(expense), 0);
      return { name, expenses: centerExpenses, assigned, hasBudget: assignedValue != null, total, difference: total - assigned };
    });
  }, [expenses, item]);

  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !item) return;
    setSaving(true);
    const form = new FormData(event.currentTarget);
    const costCenters = String(form.get("cost_centers") || "").split(/\n|,/).map((value) => value.trim()).filter(Boolean);
    try {
      await apiRequest(`/cases/${caseId}`, { method: "PUT", body: { ...item, company_id: form.get("company_id"), closure_method: form.get("closure_method"), cost_centers: costCenters }, token });
      setEditing(false); fetchCase();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "No se pudo guardar."); }
    finally { setSaving(false); }
  }

  async function caseAction(action: "request_user_confirmation" | "resolve_settlement" | "close_rendicion") {
    if (!token) return;
    setActionLoading(action); setError("");
    try { await apiRequest(`/cases/${caseId}/actions`, { method: "POST", body: { action }, token }); fetchCase(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "No se pudo completar la acción."); }
    finally { setActionLoading(""); }
  }

  async function expenseAction(expenseId: string, action: "approve" | "reject", reason?: string) {
    if (!token) return;
    setExpenseLoading(`${expenseId}:${action}`); setError("");
    try {
      await apiRequest(`/expenses/${expenseId}/actions`, { method: "POST", body: { action, ...(reason ? { reason } : {}) }, token });
      setRejectIds(null); fetchCase();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "No se pudo actualizar el gasto."); }
    finally { setExpenseLoading(""); }
  }

  async function bulkReject(reason: string) {
    if (!token || !rejectIds) return;
    setExpenseLoading("bulk:reject");
    try {
      for (const id of rejectIds) await apiRequest(`/expenses/${id}/actions`, { method: "POST", body: { action: "reject", reason }, token });
      setRejectIds(null); setSelected(new Set()); fetchCase();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "No se pudieron rechazar los gastos."); }
    finally { setExpenseLoading(""); }
  }

  async function downloadPdf() {
    if (!token) return;
    setDocumentLoading(true);
    try {
      const result = await apiRequest<{ signed_url?: string }>(`/cases/${caseId}/consolidated-document`, { method: "POST", token });
      if (!result.signed_url) throw new Error("El documento no incluyó una URL de descarga.");
      window.open(result.signed_url, "_blank", "noopener,noreferrer");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "No se pudo generar el PDF."); }
    finally { setDocumentLoading(false); }
  }

  function renderExpenses(list: Expense[], showCenter = false) {
    return list.length ? (
      <div className="overflow-hidden rounded-2xl border border-slate-200 shadow-sm">
        {list.map((expense) => (
          <ExpenseRow
            key={expense.expense_id}
            expense={expense}
            selected={selected.has(expense.expense_id)}
            loading={expenseLoading}
            showCenter={showCenter}
            onSelect={() => setSelected((previous) => {
              const next = new Set(previous);
              next.has(expense.expense_id) ? next.delete(expense.expense_id) : next.add(expense.expense_id);
              return next;
            })}
            onApprove={() => {
              if (window.confirm(`¿Aprobar el gasto de ${expense.merchant || "comercio no identificado"}?`)) {
                expenseAction(expense.expense_id, "approve");
              }
            }}
            onReject={() => setRejectIds([expense.expense_id])}
          />
        ))}
      </div>
    ) : <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">Sin gastos registrados.</div>;
  }

  return (
    <ProtectedPage>
      <Shell title="" description="">
        {!item ? (
          <div className="flex items-center gap-2 rounded-xl border bg-white p-4 text-sm text-slate-600">
            <LoaderCircle className="h-4 w-4 animate-spin" /> Cargando rendición…
          </div>
        ) : (
          <main className="space-y-5">
            <header className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-xs text-slate-500">
                <Link href="/cases" className="hover:text-primary-700">Rendiciones</Link>
                <ChevronRight className="h-3.5 w-3.5" /><span>Detalle</span>
              </nav>
              <div className="mt-3">
                <div className="flex flex-wrap items-center gap-3">
                  <h1 className="text-2xl font-bold tracking-tight text-slate-950">Rendición: {item.context_label || caseId}</h1>
                  <Badge tone={status}>{humanizeStatus(status)}</Badge>
                </div>
                <p className="mt-1 text-sm text-slate-500">
                  Responsable: <span className="font-medium text-slate-700">{employee?.name || "Sin persona asociada"}</span>
                  {" · "}Creada: {formatDate(item.created_at)}
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {status === "open" && (
                    <button className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-3.5 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50" onClick={() => caseAction("request_user_confirmation")} disabled={Boolean(actionLoading)} type="button">
                      <Send className="h-4 w-4" /> {actionLoading ? "Enviando…" : item.closure_method === "simple" ? "Solicitar confirmación" : "Solicitar firma"}
                    </button>
                  )}
                  {status === "approved" && item.settlement_status === "settlement_pending" && (
                    <button className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-3.5 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50" onClick={() => caseAction("resolve_settlement")} disabled={Boolean(actionLoading)} type="button">
                      <CircleDollarSign className="h-4 w-4" /> {actionLoading ? "Registrando…" : "Resolver liquidación"}
                    </button>
                  )}
                  <button className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3.5 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50" onClick={downloadPdf} disabled={documentLoading || expenses.length === 0} type="button">
                    <Download className="h-4 w-4" /> {documentLoading ? "Generando…" : "Descargar PDF"}
                  </button>
                  <button className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3.5 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50" onClick={() => setEditing((value) => !value)} type="button">
                    <Pencil className="h-4 w-4" /> {editing ? "Cancelar edición" : "Editar"}
                  </button>
                  {status === "approved" && item.settlement_status !== "settlement_pending" && (
                    <button className="inline-flex items-center gap-2 rounded-lg border border-red-200 px-3.5 py-2 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50" onClick={() => window.confirm("¿Cerrar esta rendición? Esta acción es irreversible.") && caseAction("close_rendicion")} disabled={Boolean(actionLoading)} type="button">
                      <Lock className="h-4 w-4" /> {actionLoading ? "Cerrando…" : "Cerrar rendición"}
                    </button>
                  )}
                </div>
              </div>
            </header>

            {editing && (
              <form className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 md:grid-cols-2" onSubmit={saveEdit}>
                <label className="text-sm font-medium text-slate-700">Empresa
                  <input className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2" name="company_id" defaultValue={item.company_id || ""} />
                </label>
                <label className="text-sm font-medium text-slate-700">Método de cierre
                  <select className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2" name="closure_method" defaultValue={item.closure_method || "docusign"}>
                    {Object.entries(CLOSURE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
                <label className="text-sm font-medium text-slate-700 md:col-span-2">Centros de costo
                  <textarea className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2" name="cost_centers" rows={3} defaultValue={(item.cost_centers || []).join("\n")} />
                </label>
                <button className="w-fit rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={saving} type="submit">{saving ? "Guardando…" : "Guardar cambios"}</button>
              </form>
            )}

            {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>}

            <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <MetricCard label="Presupuesto total" value={budget > 0 ? formatClp(budget) : "No informado"} icon={WalletCards} />
              <MetricCard label="Gastado total" value={formatClp(spent)} detail={`${expenses.length} gasto${expenses.length === 1 ? "" : "s"}`} icon={Receipt} />
              <MetricCard label="Diferencia" value={difference == null ? "Sin referencia" : formatClp(Math.abs(difference))} detail={difference == null ? "Presupuesto no informado" : difference > 0 ? `Sobre presupuesto por ${formatClp(difference)}` : `${formatClp(Math.abs(difference))} disponibles`} icon={AlertTriangle} tone={difference == null ? "neutral" : difference > 0 ? "danger" : "success"} />
              <MetricCard label="Centros de costo" value={centers.length ? String(centers.length) : "Sin asignar"} icon={FolderOpen} />
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2"><h2 className="font-semibold text-slate-950">Liquidación final</h2><Badge>{humanizeStatus(item.settlement_status)}</Badge></div>
                  <p className="mt-1 text-sm text-slate-600">{DIRECTION_LABELS[item.settlement_direction || ""] || "Resultado pendiente de cálculo"}</p>
                </div>
                <div className="grid grid-cols-2 gap-6 text-right">
                  <div><p className="text-xs text-slate-500">Monto</p><p className="font-bold tabular-nums">{formatClp(item.settlement_amount_clp)}</p></div>
                  <div><p className="text-xs text-slate-500">Neto</p><p className="font-bold tabular-nums">{formatClp(item.settlement_net_clp)}</p></div>
                </div>
              </div>
              <div className="mt-4">
                {percent == null ? <p className="text-sm text-slate-500">Presupuesto no informado</p> : (
                  <>
                    <div className="h-2.5 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-label="Presupuesto utilizado" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(percent, 100)}>
                      <div className={`h-full rounded-full ${percent > 100 ? "bg-red-500" : "bg-primary-600"}`} style={{ width: `${Math.min(percent, 100)}%` }} />
                    </div>
                    <div className="mt-2 flex justify-between gap-3 text-xs">
                      <span className={percent > 100 ? "font-semibold text-red-700" : "text-slate-500"}>{percent > 100 ? `Sobre presupuesto por ${formatClp(spent - budget)}` : `${percent}% del presupuesto utilizado`}</span>
                      <span className="text-slate-500">{formatClp(spent)} de {formatClp(budget)}</span>
                    </div>
                  </>
                )}
              </div>
            </section>

            {selected.size > 0 && (
              <div className="sticky top-3 z-20 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary-200 bg-primary-50 p-3 shadow-lg">
                <span className="text-sm font-semibold text-primary-800">{selected.size} seleccionado{selected.size === 1 ? "" : "s"}</span>
                <div className="flex gap-2">
                  <button className="rounded-lg bg-red-600 px-3 py-2 text-sm font-semibold text-white" onClick={() => setRejectIds(Array.from(selected))} type="button">Rechazar</button>
                  <button className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold" onClick={() => setSelected(new Set())} type="button">Cancelar</button>
                </div>
              </div>
            )}

            <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,7fr)_minmax(300px,3fr)]">
              <section className="min-w-0 space-y-4">
                <div className="flex gap-1 rounded-xl bg-slate-100 p-1" role="tablist" aria-label="Vista de gastos">
                  {([["centers", "Resumen por centros"], ["all", "Todos los gastos"]] as const).map(([value, label]) => (
                    <button key={value} className={`flex-1 rounded-lg px-3 py-2 text-sm font-semibold ${activeTab === value ? "bg-white text-slate-950 shadow-sm" : "text-slate-500 hover:text-slate-800"}`} onClick={() => setActiveTab(value)} role="tab" aria-selected={activeTab === value} type="button">{label}</button>
                  ))}
                </div>
                {activeTab === "all" ? renderExpenses(expenses, true) : (
                  <div className="space-y-3">
                    {centers.length === 0 && renderExpenses([])}
                    {centers.map((center) => {
                      const expanded = expandedCenters[center.name] !== false;
                      const over = center.hasBudget && center.difference > 0;
                      return (
                        <article key={center.name} className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
                          <button className="flex w-full flex-col gap-4 p-4 text-left sm:flex-row sm:items-center sm:justify-between" onClick={() => setExpandedCenters((current) => ({ ...current, [center.name]: !expanded }))} type="button" aria-expanded={expanded}>
                            <div className="flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-50 text-primary-700"><Landmark className="h-5 w-5" /></span><div><h3 className="font-semibold text-slate-950">{center.name}</h3><p className="text-xs text-slate-500">{center.expenses.length} gasto{center.expenses.length === 1 ? "" : "s"}</p></div></div>
                            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
                              <div><span className="text-slate-500">Presupuesto</span><p className="font-semibold">{center.hasBudget ? formatClp(center.assigned) : "Sin presupuesto asignado"}</p></div>
                              <div><span className="text-slate-500">Gastado</span><p className="font-semibold">{formatClp(center.total)}</p></div>
                              {center.hasBudget && <div><span className="text-slate-500">Diferencia</span><p className={`font-semibold ${over ? "text-red-700" : "text-emerald-700"}`}>{over ? `Exceso ${formatClp(center.difference)}` : `${formatClp(Math.abs(center.difference))} disponible`}</p></div>}
                              <ChevronDown className={`h-4 w-4 text-slate-400 transition ${expanded ? "rotate-180" : ""}`} />
                            </div>
                          </button>
                          {expanded && renderExpenses(center.expenses)}
                        </article>
                      );
                    })}
                  </div>
                )}
              </section>

              <aside className="space-y-4">
                <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                  <h2 className="text-sm font-semibold text-slate-950">Persona asociada</h2>
                  {employee ? (
                    <div className="mt-3">
                      <div className="flex items-center gap-3">
                        <span className="flex h-11 w-11 items-center justify-center rounded-full bg-primary-100 font-semibold text-primary-700">{employee.name?.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || <UserRound className="h-5 w-5" />}</span>
                        <div className="min-w-0"><p className="truncate font-semibold text-slate-900">{employee.name}</p><p className="text-sm text-slate-500">{employee.phone}</p></div>
                      </div>
                      {employee.company_id && <p className="mt-3 text-sm text-slate-600">Empresa: <span className="font-medium text-slate-800">{employee.company_id}</span></p>}
                      <Link className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-primary-700 hover:text-primary-800" href={`/employees/${encodeURIComponent(employee.phone)}`}>Ver persona <ChevronRight className="h-4 w-4" /></Link>
                    </div>
                  ) : <p className="mt-3 text-sm text-slate-500">Sin persona vinculada.</p>}
                </section>

                <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                  <div className="flex items-start justify-between gap-3"><div><h2 className="text-sm font-semibold text-slate-950">Estado y actividad</h2><p className="mt-1 text-sm text-slate-600">{humanizeStatus(conversationState || item.status)}</p></div><Clock3 className="h-4 w-4 text-slate-400" /></div>
                  <div className="mt-4 space-y-0">
                    {(showAllActivity ? timeline : timeline.slice(0, 6)).map((event) => (
                      <div key={`${event.date}-${event.label}-${event.detail || ""}`} className="relative flex gap-3 pb-4 last:pb-0">
                        <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${event.tone === "success" ? "bg-emerald-500" : event.tone === "danger" ? "bg-red-500" : "bg-slate-400"}`} />
                        <div className="min-w-0"><p className="text-sm font-medium text-slate-800">{event.label}</p>{event.detail && <p className="truncate text-xs text-slate-500">{event.detail}</p>}<p className="text-xs text-slate-400">{formatDate(event.date, true)}</p></div>
                      </div>
                    ))}
                  </div>
                  {timeline.length > 6 && <button className="mt-4 text-sm font-semibold text-primary-700" onClick={() => setShowAllActivity((value) => !value)} type="button">{showAllActivity ? "Ver menos" : "Ver toda la actividad"}</button>}
                </section>

                {(item.employee_phone || item.phone) && <ChatPanel phone={item.employee_phone || item.phone || ""} maxHeight="420px" onMessageSent={fetchCase} />}
              </aside>
            </div>
          </main>
        )}
        {rejectIds && (
          <RejectExpenseDialog
            title={rejectIds.length > 1 ? "Rechazar gastos seleccionados" : "Rechazar gasto"}
            description="Selecciona el motivo del rechazo. La persona será notificada por WhatsApp."
            loading={Boolean(expenseLoading)}
            onCancel={() => setRejectIds(null)}
            onConfirm={(reason) => rejectIds.length === 1 ? expenseAction(rejectIds[0], "reject", reason) : bulkReject(reason)}
          />
        )}
      </Shell>
    </ProtectedPage>
  );
}
