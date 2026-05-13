"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import {
  AlertTriangle,
  Bus,
  Camera,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  ClipboardCheck,
  Clock,
  Eye,
  FileText,
  FolderOpen,
  LoaderCircle,
  Lock,
  Pencil,
  PlusCircle,
  Send,
  ShieldCheck,
  TrendingUp,
  Users,
  Wallet,
  XCircle,
} from "lucide-react";

import { ChatPanel } from "@/components/chat-panel";
import { Badge } from "@/components/badge";
import { ProtectedPage } from "@/components/protected-page";
import { RejectExpenseDialog } from "@/components/reject-expense-dialog";
import { Shell } from "@/components/shell";
import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api";
import { useAutoRefresh } from "@/lib/use-auto-refresh";
import type { CaseItem, Employee, Expense } from "@/lib/types";

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

const CC_COLORS: { bg: string; icon: string; iconColor: string; bar: string }[] = [
  { bg: "bg-rose-100", icon: "bg-rose-500", iconColor: "text-white", bar: "bg-rose-500" },
  { bg: "bg-emerald-100", icon: "bg-emerald-500", iconColor: "text-white", bar: "bg-emerald-500" },
  { bg: "bg-amber-100", icon: "bg-amber-500", iconColor: "text-white", bar: "bg-amber-500" },
  { bg: "bg-blue-100", icon: "bg-blue-500", iconColor: "text-white", bar: "bg-blue-500" },
  { bg: "bg-violet-100", icon: "bg-violet-500", iconColor: "text-white", bar: "bg-violet-500" },
  { bg: "bg-cyan-100", icon: "bg-cyan-500", iconColor: "text-white", bar: "bg-cyan-500" },
];

const CC_ICON_MAP: Record<string, React.ElementType> = {
  actores: Users,
  fotografo: Camera,
  fotógrafo: Camera,
  transporte: Bus,
  transport: Bus,
};

function getCcIcon(centerName: string): React.ElementType {
  const key = centerName.toLowerCase().trim();
  return CC_ICON_MAP[key] ?? FolderOpen;
}

function formatCLP(value?: number | string): string {
  const num = typeof value === "string" ? parseFloat(value) : value;
  if (num == null || isNaN(num)) return "-";
  return `$${num.toLocaleString("es-CL", { maximumFractionDigits: 0 })}`;
}

function formatDateShort(iso?: string): string {
  if (!iso) return "-";
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  return d.toLocaleDateString("es-CL", { day: "numeric", month: "short", year: "numeric" });
}

function parseAmount(value?: number | string): number {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  if (typeof value !== "string") return 0;
  const normalized = value.replace(/\./g, "").replace(",", ".");
  const amount = parseFloat(normalized);
  return Number.isFinite(amount) ? amount : 0;
}

function ScoreBadge({ score }: { score?: number }) {
  if (score == null) return <span className="text-xs text-gray-400">-</span>;
  let color = "bg-red-100 text-red-700";
  let label = "Revisar";
  if (score >= 80) { color = "bg-emerald-100 text-emerald-700"; label = "Alta confianza"; }
  else if (score >= 50) { color = "bg-amber-100 text-amber-700"; label = "Media confianza"; }
  return (
    <div className="text-center">
      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-bold ${color}`}>
        {score}
      </span>
      <p className="mt-0.5 text-[10px] text-gray-400">{label}</p>
    </div>
  );
}

function MobileExpenseList({
  expenses,
  selectedExpenses,
  expenseActionLoading,
  onToggleSelect,
  onApprove,
  onReject,
  showCostCenter,
}: {
  expenses: Expense[];
  selectedExpenses: Set<string>;
  expenseActionLoading: string;
  onToggleSelect: (id: string) => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  showCostCenter?: boolean;
}) {
  return (
    <div className="divide-y divide-gray-100">
      {expenses.map((expense) => {
        const isApproved = expense.review_status === "approved";
        const isRejected = expense.review_status === "rejected";
        const isPending = !isApproved && !isRejected;
        const docType =
          expense.document_type === "invoice"
            ? "Factura"
            : expense.document_type === "professional_fee_receipt"
              ? "Honorarios"
              : "Boleta";
        return (
          <div
            key={expense.expense_id}
            className={`px-4 py-3.5 ${selectedExpenses.has(expense.expense_id) ? "bg-primary-50/40" : ""}`}
          >
            <div className="flex items-start gap-3">
              {isPending && (
                <input
                  type="checkbox"
                  checked={selectedExpenses.has(expense.expense_id)}
                  onChange={() => onToggleSelect(expense.expense_id)}
                  className="mt-1.5 h-5 w-5 flex-shrink-0 rounded border-gray-300 accent-primary-600"
                />
              )}
              <Link href={`/expenses/${expense.expense_id}`} className="flex-shrink-0">
                {expense.image_url ? (
                  <img src={expense.image_url} alt="" className="h-12 w-12 rounded-xl border border-gray-200 object-cover" loading="lazy" />
                ) : (
                  <span className="flex h-12 w-12 items-center justify-center rounded-xl border border-gray-200 bg-gray-50 text-gray-400">
                    <FileText className="h-5 w-5" />
                  </span>
                )}
              </Link>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <Link href={`/expenses/${expense.expense_id}`} className="min-w-0 truncate text-sm font-semibold text-gray-900 hover:text-primary-700">
                    {expense.merchant || "Documento sin identificar"}
                  </Link>
                  <p className="flex-shrink-0 text-sm font-bold text-gray-900">
                    {expense.total_clp ? formatCLP(expense.total_clp) : `${expense.currency || ""} ${expense.total || "-"}`}
                  </p>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  {isApproved ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                      <CheckCircle className="h-3 w-3" /> Aprobado
                    </span>
                  ) : isRejected ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
                      <XCircle className="h-3 w-3" /> Rechazado
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
                      <Clock className="h-3 w-3" /> Pendiente
                    </span>
                  )}
                  <ScoreBadge score={expense.review_score} />
                  <span className="text-xs text-gray-400">{formatDateShort(expense.date)}</span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <span className="inline-flex rounded-md border border-primary-200 bg-primary-50 px-1.5 py-0.5 text-[10px] font-medium text-primary-700">
                    {docType}
                  </span>
                  {showCostCenter && expense.cost_center && (
                    <span className="text-xs text-gray-400">{expense.cost_center}</span>
                  )}
                </div>
              </div>
            </div>
            {isPending && (
              <div className="mt-3 grid grid-cols-2 gap-2">
                <button
                  className="flex items-center justify-center gap-1.5 rounded-xl border border-emerald-200 bg-emerald-50 py-3 text-sm font-semibold text-emerald-700 transition active:bg-emerald-100 disabled:opacity-50"
                  disabled={!!expenseActionLoading}
                  onClick={() => onApprove(expense.expense_id)}
                  type="button"
                >
                  <CheckCircle className="h-4 w-4" /> Aprobar
                </button>
                <button
                  className="flex items-center justify-center gap-1.5 rounded-xl border border-red-200 bg-red-50 py-3 text-sm font-semibold text-red-700 transition active:bg-red-100 disabled:opacity-50"
                  disabled={!!expenseActionLoading}
                  onClick={() => onReject(expense.expense_id)}
                  type="button"
                >
                  <XCircle className="h-4 w-4" /> Rechazar
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function StatCard({
  label,
  value,
  icon: Icon,
  iconBg,
  iconColor,
  valueColor,
  sub,
}: {
  label: string;
  value: string;
  icon: React.ElementType;
  iconBg: string;
  iconColor: string;
  valueColor?: string;
  sub?: string;
}) {
  return (
    <div className="flex min-w-0 flex-col items-start gap-2 rounded-xl border border-gray-100 bg-white px-3 py-3 shadow-sm sm:flex-row sm:items-center sm:gap-4 sm:rounded-2xl sm:px-5 sm:py-4">
      <div className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full sm:h-11 sm:w-11 ${iconBg}`}>
        <Icon className={`h-4 w-4 sm:h-5 sm:w-5 ${iconColor}`} />
      </div>
      <div className="min-w-0 w-full">
        <p className="text-[11px] font-medium leading-tight text-gray-500 sm:text-xs">{label}</p>
        <p className={`max-w-full break-words text-[clamp(0.75rem,3.2vw,1.25rem)] font-bold leading-tight tabular-nums sm:whitespace-nowrap sm:text-xl ${valueColor ?? "text-gray-900"}`}>
          {value}
        </p>
        {sub && <p className="mt-0.5 text-[11px] leading-tight text-gray-400 sm:text-xs">{sub}</p>}
      </div>
    </div>
  );
}

type TimelineEvent = {
  date: string;
  label: string;
  detail?: string;
  icon: React.ElementType;
  tone: "default" | "success" | "warning" | "error";
};

type RejectConfirm = {
  ids: string[];
} | null;

function buildTimeline(item: CaseItem, expenses: Expense[]): TimelineEvent[] {
  const events: TimelineEvent[] = [];
  if (item.created_at) events.push({ date: item.created_at, label: "Rendición creada", icon: PlusCircle, tone: "default" });
  for (const exp of expenses) {
    if (exp.created_at) events.push({ date: exp.created_at, label: "Documento subido", detail: exp.merchant || exp.expense_id, icon: FileText, tone: "default" });
    if (exp.review_status === "approved" && exp.updated_at) events.push({ date: exp.updated_at, label: "Documento aprobado", detail: exp.merchant || exp.expense_id, icon: CheckCircle, tone: "success" });
    if (exp.review_status === "rejected" && exp.updated_at) events.push({ date: exp.updated_at, label: "Documento rechazado", detail: exp.merchant || exp.expense_id, icon: XCircle, tone: "error" });
  }
  if (["pending_user_confirmation", "approved", "closed"].includes(item.rendicion_status || "")) {
    events.push({ date: item.updated_at || item.created_at || "", label: item.closure_method === "simple" ? "Enviado a confirmación" : "Enviado a firma", detail: item.closure_method === "simple" ? "Confirmación WhatsApp" : "DocuSign", icon: Send, tone: "warning" });
  }
  if (item.user_confirmed_at) events.push({ date: item.user_confirmed_at, label: item.closure_method === "simple" ? "Confirmado por usuario" : "Firmado por usuario", icon: ShieldCheck, tone: "success" });
  if (item.rendicion_status === "approved" && item.updated_at) events.push({ date: item.updated_at, label: "Rendición aprobada", icon: ClipboardCheck, tone: "success" });
  if (item.rendicion_status === "closed" && item.updated_at) events.push({ date: item.updated_at, label: "Rendición cerrada", icon: Lock, tone: "default" });
  events.sort((a, b) => a.date.localeCompare(b.date));
  return events;
}

const toneIcon: Record<string, string> = {
  default: "text-gray-500",
  success: "text-emerald-600",
  warning: "text-amber-600",
  error: "text-red-600",
};

export default function CaseDetailPage() {
  const params = useParams<{ caseId: string }>();
  const { token } = useAuth();
  const caseId = typeof params.caseId === "string" ? params.caseId : "";
  const [item, setItem] = useState<CaseItem | null>(null);
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [saving, setSaving] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [actionLoading, setActionLoading] = useState("");
  const [expenseActionLoading, setExpenseActionLoading] = useState("");
  const [bulkActionLoading, setBulkActionLoading] = useState(false);
  const [selectedExpenses, setSelectedExpenses] = useState<Set<string>>(new Set());
  const [rejectConfirm, setRejectConfirm] = useState<RejectConfirm>(null);
  const [actionError, setActionError] = useState("");
  const [closeRendicionPopupError, setCloseRendicionPopupError] = useState("");
  const [expandedCenters, setExpandedCenters] = useState<Record<string, boolean>>({});
  const [activeTab, setActiveTab] = useState<"centers" | "all">("centers");

  function fetchCase() {
    if (!token || !caseId) return;
    apiRequest<{ case: CaseItem; employee: Employee; expenses: Expense[]; conversations: unknown[] }>(
      `/cases/${caseId}`, { token }
    ).then((data) => {
      setActionError("");
      setItem(data.case);
      setEmployee(data.employee);
      setExpenses(data.expenses);
    });
  }

  useEffect(() => { fetchCase(); }, [caseId, token]);
  useAutoRefresh(() => fetchCase(), { enabled: Boolean(token) && Boolean(caseId) && !saving && !isEditing && !actionLoading });

  async function onSubmitEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !item) return;
    setSaving(true);
    try {
      const form = new FormData(event.currentTarget);
      const payload = Object.fromEntries(form.entries());
      const costCenters = String(payload.cost_centers || "").split(/\n|,/).map((c) => c.trim()).filter(Boolean);
      await apiRequest(`/cases/${caseId}`, { method: "PUT", body: { ...item, ...payload, cost_centers: costCenters, employee_phone: item.employee_phone || item.phone }, token });
      setIsEditing(false);
      fetchCase();
    } finally {
      setSaving(false);
    }
  }

  async function runAction(action: "close" | "request_user_confirmation" | "resolve_settlement" | "close_rendicion") {
    if (!token) return;
    setActionLoading(action);
    setActionError("");
    if (action === "close_rendicion") setCloseRendicionPopupError("");
    try {
      await apiRequest(`/cases/${caseId}/actions`, { method: "POST", body: { action }, token });
      fetchCase();
    } catch (error) {
      const message = error instanceof Error ? error.message : "No se pudo completar la acción sobre la rendición.";
      if (action === "close_rendicion") setCloseRendicionPopupError(message);
      else setActionError(message);
    } finally {
      setActionLoading("");
    }
  }

  async function runExpenseAction(expenseId: string, action: "approve" | "reject", reason?: string) {
    if (!token) return;
    setExpenseActionLoading(`${expenseId}:${action}`);
    setActionError("");
    try {
      await apiRequest(`/expenses/${expenseId}/actions`, {
        method: "POST",
        body: { action, ...(reason ? { reason } : {}) },
        token,
      });
      setRejectConfirm(null);
      fetchCase();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "No se pudo actualizar el gasto.");
    } finally {
      setExpenseActionLoading("");
    }
  }

  async function runBulkAction(action: "approve" | "reject", reason?: string) {
    if (!token || selectedExpenses.size === 0) return;
    setBulkActionLoading(true);
    setActionError("");
    try {
      for (const expenseId of Array.from(selectedExpenses)) {
        await apiRequest(`/expenses/${expenseId}/actions`, {
          method: "POST",
          body: { action, ...(reason ? { reason } : {}) },
          token,
        });
      }
      setSelectedExpenses(new Set());
      setRejectConfirm(null);
      fetchCase();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "No se pudo completar la acción masiva.");
    } finally {
      setBulkActionLoading(false);
    }
  }

  function toggleExpenseSelection(expenseId: string) {
    setSelectedExpenses((prev) => {
      const next = new Set(prev);
      if (next.has(expenseId)) next.delete(expenseId);
      else next.add(expenseId);
      return next;
    });
  }

  const rendStatus = item?.rendicion_status || "open";
  const fondos = typeof item?.fondos_entregados === "string" ? parseFloat(item.fondos_entregados) || 0 : item?.fondos_entregados || 0;
  const saldo = item?.saldo_restante ?? 0;
  const settlementDirection = item?.settlement_direction || "";
  const settlementStatus = item?.settlement_status || "";
  const settlementAmount = item?.settlement_amount_clp;
  const settlementNet = item?.settlement_net_clp;
  const showSettlementCard = rendStatus === "approved" || rendStatus === "closed" || Boolean(settlementStatus);

  const declaredCostCenters = item?.cost_centers || [];
  const costCenterNames = Array.from(new Set([
    ...declaredCostCenters.map((c) => c.trim()).filter(Boolean),
    ...Object.keys(item?.fondos_por_centro || {}).map((c) => c.trim()).filter(Boolean),
    ...expenses.map((e) => e.cost_center?.trim()).filter((c): c is string => Boolean(c)),
  ]));
  if (expenses.some((e) => !e.cost_center?.trim()) && !costCenterNames.includes("Sin centro de costo")) {
    costCenterNames.push("Sin centro de costo");
  }

  const expensesByCostCenter = costCenterNames.map((center, idx) => {
    const centerExpenses = expenses.filter((e) => (e.cost_center?.trim() || "Sin centro de costo") === center);
    const assignedRaw = item?.fondos_por_centro?.[center];
    const renderedClp = centerExpenses.reduce((sum, e) => {
      return sum + (parseAmount(e.total_clp) || (e.currency === "CLP" ? parseAmount(e.total) : 0));
    }, 0);
    const assignedClp = parseAmount(assignedRaw);
    const hasAssigned = assignedRaw != null;
    const diff = hasAssigned ? renderedClp - assignedClp : null;
    const pct = hasAssigned && assignedClp > 0 ? Math.round((renderedClp / assignedClp) * 100) : null;
    const isOver = pct != null && pct > 100;
    return { center, assignedClp, hasAssigned, count: centerExpenses.length, expenses: centerExpenses, renderedClp, diff, pct, isOver, colorIdx: idx % CC_COLORS.length };
  }).sort((a, b) => {
    const ai = declaredCostCenters.indexOf(a.center);
    const bi = declaredCostCenters.indexOf(b.center);
    if (ai >= 0 || bi >= 0) {
      if (ai >= 0 && bi >= 0) return ai - bi;
      return ai >= 0 ? -1 : 1;
    }
    return b.renderedClp - a.renderedClp || a.center.localeCompare(b.center);
  });

  const totalRendido = expenses.reduce((sum, e) => sum + (parseAmount(e.total_clp) || (e.currency === "CLP" ? parseAmount(e.total) : 0)), 0);
  const diffGlobal = fondos > 0 ? totalRendido - fondos : null;
  const globalSpentPct = fondos > 0 ? Math.round((totalRendido / fondos) * 100) : null;
  const globalProgressPct = globalSpentPct != null ? Math.min(globalSpentPct, 100) : totalRendido > 0 ? 100 : 0;
  const globalIsOverBudget = globalSpentPct != null && globalSpentPct > 100;
  const globalBalance = fondos - totalRendido;

  return (
    <ProtectedPage>
      <Shell title="" description="">
        {/* Error popup */}
        {closeRendicionPopupError && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/40 px-4">
            <div aria-modal="true" role="dialog" className="w-full max-w-md rounded-2xl border border-red-100 bg-white shadow-2xl">
              <div className="flex items-start justify-between gap-4 border-b border-gray-100 px-5 py-4">
                <div>
                  <h2 className="text-base font-semibold text-gray-900">No se pudo cerrar la rendición</h2>
                  <p className="mt-1 text-sm text-gray-500">Revisa la condición pendiente antes de intentar nuevamente.</p>
                </div>
                <button aria-label="Cerrar popup" className="rounded-lg p-2 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700" onClick={() => setCloseRendicionPopupError("")} type="button">
                  <XCircle className="h-5 w-5" />
                </button>
              </div>
              <div className="px-5 py-4">
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{closeRendicionPopupError}</div>
                <div className="mt-5 flex justify-end">
                  <button className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700" onClick={() => setCloseRendicionPopupError("")} type="button">Entendido</button>
                </div>
              </div>
            </div>
          </div>
        )}

        {!item && (
          <div className="flex items-center gap-2 rounded-xl border border-primary-100 bg-white px-5 py-4 text-sm font-medium text-gray-700 shadow-sm" role="status" aria-live="polite">
            <LoaderCircle className="h-4 w-4 animate-spin text-primary-600" />
            Cargando rendición...
          </div>
        )}

        {item && (
          <div className="space-y-4 sm:space-y-6">
            {/* ── Header ── */}
            <div className="flex flex-wrap items-start justify-between gap-3 sm:gap-4">
              <div className="min-w-0">
                <h1 className="break-words text-xl font-bold leading-tight text-gray-900 sm:text-2xl">
                  Rendición: {item.context_label || caseId}
                </h1>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-gray-500 sm:gap-3">
                  {employee && (
                    <span className="flex items-center gap-1.5">
                      <Users className="h-3.5 w-3.5" />
                      Responsable: {employee.name}
                    </span>
                  )}
                  {item.created_at && (
                    <span className="flex items-center gap-1.5">
                      <Clock className="h-3.5 w-3.5" />
                      Creada: {formatDateShort(item.created_at)}
                    </span>
                  )}
                  <Badge>{rendicionStatusLabels[rendStatus] || rendStatus}</Badge>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50 sm:px-3.5 sm:py-2"
                  onClick={() => setIsEditing((v) => !v)}
                  type="button"
                >
                  <Pencil className="h-4 w-4" />
                  {isEditing ? "Cancelar" : "Editar"}
                </button>
              </div>
            </div>

            {/* ── Edit form ── */}
            {isEditing && (
              <form className="grid grid-cols-1 gap-4 rounded-2xl border border-gray-200 bg-gray-50 p-5 lg:grid-cols-[minmax(0,1fr)_220px_140px]" onSubmit={onSubmitEdit}>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">Empresa asociada</label>
                  <input defaultValue={item.company_id || ""} name="company_id" className="block w-full rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100" />
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">Método de cierre</label>
                  <select defaultValue={String(item.closure_method || "docusign")} name="closure_method" className="block w-full rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100">
                    {Object.entries(closureMethodLabels).map(([value, label]) => (<option key={value} value={value}>{label}</option>))}
                  </select>
                </div>
                <div className="lg:col-span-3">
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">Centros de costo</label>
                  <textarea defaultValue={(item.cost_centers || []).join("\n")} name="cost_centers" rows={3} className="block w-full resize-none rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100" />
                </div>
                <div className="flex items-end">
                  <button className="w-full rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700 disabled:opacity-50" type="submit" disabled={saving}>
                    {saving ? "Guardando..." : "Guardar"}
                  </button>
                </div>
              </form>
            )}

            {/* ── Summary stat cards ── */}
            <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
              <StatCard label="Presupuesto total" value={fondos > 0 ? formatCLP(fondos) : "-"} icon={Wallet} iconBg="bg-gray-100" iconColor="text-gray-600" />
              <StatCard label="Gastado total" value={formatCLP(totalRendido)} icon={TrendingUp} iconBg="bg-rose-100" iconColor="text-rose-600" />
              <StatCard
                label="Diferencia"
                value={diffGlobal != null ? `${diffGlobal >= 0 ? "+" : ""}${formatCLP(diffGlobal)}` : "-"}
                sub={fondos > 0 && diffGlobal != null ? `${Math.round((totalRendido / fondos) * 100)}% del presupuesto` : undefined}
                icon={AlertTriangle}
                iconBg={diffGlobal != null && diffGlobal > 0 ? "bg-red-100" : "bg-emerald-100"}
                iconColor={diffGlobal != null && diffGlobal > 0 ? "text-red-600" : "text-emerald-600"}
                valueColor={diffGlobal != null && diffGlobal > 0 ? "text-red-600" : diffGlobal != null && diffGlobal < 0 ? "text-emerald-600" : "text-gray-900"}
              />
              <StatCard label="Centros de costo" value={String(expensesByCostCenter.length)} icon={FolderOpen} iconBg="bg-indigo-100" iconColor="text-indigo-600" />
            </div>

            {/* ── Settlement card ── */}
            {showSettlementCard && (settlementDirection || settlementStatus) && (
              <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4 shadow-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-gray-900">Liquidación final</span>
                  {settlementStatus && <Badge>{settlementStatusLabels[settlementStatus] || settlementStatus}</Badge>}
                </div>
                <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Resultado</p>
                    <p className="mt-1 text-sm font-medium text-gray-900">{settlementDirectionLabels[settlementDirection] || settlementDirection || "-"}</p>
                  </div>
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Monto liquidación</p>
                    <p className="mt-1 text-sm font-medium text-gray-900">{formatCLP(settlementAmount)}</p>
                  </div>
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Neto</p>
                    <p className="mt-1 text-sm font-medium text-gray-900">{formatCLP(settlementNet)}</p>
                  </div>
                </div>
              </div>
            )}

            {/* ── Actions ── */}
            {(rendStatus === "open" || rendStatus === "pending_user_confirmation" || rendStatus === "approved") && (
              <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
                {rendStatus === "open" && (
                  <button className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-primary-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700 disabled:opacity-50 sm:w-auto sm:py-2.5" onClick={() => runAction("request_user_confirmation")} disabled={actionLoading === "request_user_confirmation"} type="button">
                    <Send className="h-4 w-4" />
                    {actionLoading === "request_user_confirmation" ? "Enviando..." : item.closure_method === "simple" ? "Solicitar confirmación al usuario" : "Solicitar firma al usuario"}
                  </button>
                )}
                {rendStatus === "pending_user_confirmation" && (
                  <span className="inline-flex items-center gap-1.5 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-700 sm:py-2.5">
                    <FileText className="h-4 w-4 flex-shrink-0" />
                    {item.closure_method === "simple" ? "Esperando confirmación del usuario por WhatsApp" : "Esperando firma del usuario via DocuSign"}
                  </span>
                )}
                {rendStatus === "approved" && (
                  <>
                    {settlementStatus === "settlement_pending" && (
                      <button className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-sky-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-sky-700 disabled:opacity-50 sm:w-auto sm:py-2.5" onClick={() => runAction("resolve_settlement")} disabled={actionLoading === "resolve_settlement"} type="button">
                        <ClipboardCheck className="h-4 w-4" />
                        {actionLoading === "resolve_settlement" ? "Registrando..." : "Marcar liquidación resuelta"}
                      </button>
                    )}
                    <button className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl border border-gray-300 px-4 py-3 text-sm font-semibold text-gray-700 transition hover:bg-gray-50 disabled:opacity-50 sm:w-auto sm:py-2.5" onClick={() => runAction("close_rendicion")} disabled={actionLoading === "close_rendicion"} type="button">
                      <Lock className="h-4 w-4" />
                      {actionLoading === "close_rendicion" ? "Cerrando..." : "Cerrar rendición"}
                    </button>
                  </>
                )}
              </div>
            )}
            {actionError && (
              <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{actionError}</div>
            )}

            {/* ── Bulk action bar ── */}
            {selectedExpenses.size > 0 && (
              <div className="flex flex-col gap-3 rounded-xl border border-primary-200 bg-primary-50 px-4 py-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
                <span className="text-sm font-medium text-primary-800">
                  {selectedExpenses.size} gasto{selectedExpenses.size > 1 ? "s" : ""} seleccionado{selectedExpenses.size > 1 ? "s" : ""}
                </span>
                <div className="grid grid-cols-2 gap-2 sm:flex sm:items-center sm:gap-2">
                  <button
                    className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50 sm:py-1.5"
                    disabled={bulkActionLoading}
                    onClick={() => runBulkAction("approve")}
                    type="button"
                  >
                    <CheckCircle className="h-4 w-4" />
                    {bulkActionLoading ? "Procesando..." : "Aprobar"}
                  </button>
                  <button
                    className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-red-600 px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-red-700 disabled:opacity-50 sm:py-1.5"
                    disabled={bulkActionLoading}
                    onClick={() => setRejectConfirm({ ids: Array.from(selectedExpenses) })}
                    type="button"
                  >
                    <XCircle className="h-4 w-4" />
                    {bulkActionLoading ? "Procesando..." : "Rechazar"}
                  </button>
                  <button
                    className="col-span-2 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 sm:col-span-1 sm:py-1.5"
                    onClick={() => setSelectedExpenses(new Set())}
                    type="button"
                  >
                    Cancelar
                  </button>
                </div>
              </div>
            )}

            {rejectConfirm && (
              <RejectExpenseDialog
                title={
                  rejectConfirm.ids.length > 1
                    ? "Rechazar gastos seleccionados"
                    : "Rechazar gasto"
                }
                description={
                  rejectConfirm.ids.length > 1
                    ? `Selecciona el motivo del rechazo para ${rejectConfirm.ids.length} documentos. Se notificará a cada empleado por WhatsApp.`
                    : "Selecciona el motivo del rechazo. Se notificará al empleado por WhatsApp."
                }
                loading={bulkActionLoading || Boolean(expenseActionLoading)}
                onCancel={() => setRejectConfirm(null)}
                onConfirm={(reason) => {
                  if (rejectConfirm.ids.length === 1) {
                    return runExpenseAction(rejectConfirm.ids[0], "reject", reason);
                  }
                  return runBulkAction("reject", reason);
                }}
              />
            )}

            <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-12">
              {/* ── Main content ── */}
              <div className="space-y-6 xl:col-span-8">
                {/* Tabs */}
                <div className="flex items-center gap-1 border-b border-gray-200">
                  <button
                    className={`px-4 py-2.5 text-sm font-semibold transition ${activeTab === "centers" ? "border-b-2 border-primary-600 text-primary-700" : "text-gray-500 hover:text-gray-700"}`}
                    onClick={() => setActiveTab("centers")}
                    type="button"
                  >
                    Resumen por centros
                  </button>
                  <button
                    className={`px-4 py-2.5 text-sm font-semibold transition ${activeTab === "all" ? "border-b-2 border-primary-600 text-primary-700" : "text-gray-500 hover:text-gray-700"}`}
                    onClick={() => setActiveTab("all")}
                    type="button"
                  >
                    Todos los gastos
                  </button>
                </div>

                {/* ── Cost center view ── */}
                {activeTab === "centers" && (
                  <div className="space-y-4">
                    <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4 shadow-sm">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-gray-900">Avance de gasto del caso</p>
                          <p className="mt-1 text-xs text-gray-500">
                            {globalSpentPct != null
                              ? `${globalSpentPct}% del presupuesto utilizado`
                              : "Sin presupuesto total asignado"}
                          </p>
                        </div>
                        <div className="text-right">
                          <p className="text-xs text-gray-500">Gastado total</p>
                          <p className={`text-lg font-bold ${globalIsOverBudget ? "text-red-600" : "text-gray-900"}`}>
                            {formatCLP(totalRendido)}
                          </p>
                          <p className="text-xs text-gray-400">Presupuesto {fondos > 0 ? formatCLP(fondos) : "-"}</p>
                        </div>
                      </div>
                      <div
                        aria-label="Avance de gasto total del caso"
                        aria-valuemax={fondos > 0 ? fondos : undefined}
                        aria-valuemin={0}
                        aria-valuenow={fondos > 0 ? Math.min(totalRendido, fondos) : undefined}
                        className="mt-4 h-3 w-full overflow-hidden rounded-full bg-gray-100"
                        role={fondos > 0 ? "progressbar" : undefined}
                      >
                        <div
                          className={`h-full rounded-full transition-all ${
                            globalIsOverBudget ? "bg-red-500" : fondos > 0 ? "bg-primary-600" : "bg-gray-300"
                          }`}
                          style={{ width: `${globalProgressPct}%` }}
                        />
                      </div>
                      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                        <span className={globalIsOverBudget ? "font-semibold text-red-600" : "text-gray-500"}>
                          {globalIsOverBudget
                            ? `Sobre presupuesto por ${formatCLP(Math.abs(globalBalance))}`
                            : fondos > 0
                              ? `Saldo disponible ${formatCLP(Math.max(globalBalance, 0))}`
                              : "La barra muestra gasto registrado sin compararlo contra presupuesto."}
                        </span>
                        {globalSpentPct != null && (
                          <span className="font-semibold text-gray-700">{globalSpentPct}%</span>
                        )}
                      </div>
                    </div>
                    {expensesByCostCenter.length === 0 && (
                      <p className="text-sm text-gray-500">Sin documentos para resumir.</p>
                    )}
                    {expensesByCostCenter.map((row) => {
                      const colors = CC_COLORS[row.colorIdx];
                      const CcIcon = getCcIcon(row.center);
                      const progressPct = row.pct != null ? Math.min(row.pct, 100) : 0;
                      const isExpanded = expandedCenters[row.center] !== false;

                      return (
                        <div key={row.center} className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
                          {/* CC header */}
                          <div className="px-5 py-4">
                            <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between sm:gap-4">
                              <div className="flex items-center gap-3">
                                <div className={`flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full ${colors.icon}`}>
                                  <CcIcon className={`h-5 w-5 ${colors.iconColor}`} />
                                </div>
                                <div>
                                  <p className="text-base font-bold text-gray-900">{row.center}</p>
                                  <p className="text-xs text-gray-500">{row.count} gasto{row.count === 1 ? "" : "s"}</p>
                                </div>
                              </div>
                              <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:flex sm:flex-wrap sm:items-center sm:gap-6">
                                <div>
                                  <p className="text-xs text-gray-500">Presupuesto</p>
                                  <p className="text-sm font-semibold text-gray-900">{row.hasAssigned ? formatCLP(row.assignedClp) : "-"}</p>
                                </div>
                                <div>
                                  <p className="text-xs text-gray-500">Gastado</p>
                                  <p className="text-sm font-semibold text-gray-900">{formatCLP(row.renderedClp)}</p>
                                </div>
                                {row.diff != null && (
                                  <div>
                                    <p className="text-xs text-gray-500">Diferencia</p>
                                    <p className={`text-sm font-bold ${row.isOver ? "text-red-600" : "text-emerald-600"}`}>
                                      {row.diff >= 0 ? "+" : ""}{formatCLP(row.diff)}
                                    </p>
                                  </div>
                                )}
                                {row.pct != null && (
                                  <span className={`col-span-2 inline-flex w-fit rounded-full px-3 py-1 text-xs font-bold sm:col-span-1 ${row.isOver ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"}`}>
                                    {row.pct}% del presupuesto
                                  </span>
                                )}
                              </div>
                            </div>

                            {/* Progress bar */}
                            {row.hasAssigned && row.pct != null && (
                              <div className="mt-3">
                                <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
                                  <div
                                    className={`h-full rounded-full transition-all ${row.isOver ? "bg-red-500" : "bg-emerald-500"}`}
                                    style={{ width: `${progressPct}%` }}
                                  />
                                </div>
                                {row.isOver && (
                                  <p className="mt-1 text-xs text-red-600">
                                    Has superado el presupuesto un {row.pct - 100}%
                                  </p>
                                )}
                                {!row.isOver && (
                                  <p className="mt-1 text-xs text-gray-500">Dentro del presupuesto</p>
                                )}
                              </div>
                            )}

                            {/* Action buttons */}
                            <div className="mt-4 flex items-center gap-2">
                              <button
                                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 transition hover:bg-gray-50"
                                onClick={() => setExpandedCenters((prev) => ({ ...prev, [row.center]: !isExpanded }))}
                                type="button"
                              >
                                <Eye className="h-3.5 w-3.5" />
                                {isExpanded ? "Ocultar gastos" : "Revisar gastos"}
                              </button>
                            </div>
                          </div>

                          {/* Expense list */}
                          {isExpanded && row.expenses.length > 0 && (
                            <div className="border-t border-gray-100">
                              {/* Mobile card list */}
                              <div className="sm:hidden">
                                <MobileExpenseList
                                  expenses={row.expenses}
                                  selectedExpenses={selectedExpenses}
                                  expenseActionLoading={expenseActionLoading}
                                  onToggleSelect={toggleExpenseSelection}
                                  onApprove={(id) => runExpenseAction(id, "approve")}
                                  onReject={(id) => setRejectConfirm({ ids: [id] })}
                                />
                              </div>
                              {/* Desktop table */}
                              <div className="hidden overflow-x-auto sm:block">
                                {(() => {
                                    const pendingInCenter = row.expenses.filter((e) => e.review_status !== "approved" && e.review_status !== "rejected");
                                    const allPendingSelected = pendingInCenter.length > 0 && pendingInCenter.every((e) => selectedExpenses.has(e.expense_id));
                                    return (
                                      <table className="w-full min-w-[680px]">
                                        <thead>
                                          <tr className="border-b border-gray-100 text-left text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-400">
                                            <th className="w-10 px-3 py-3">
                                              <input
                                                type="checkbox"
                                                checked={allPendingSelected}
                                                disabled={pendingInCenter.length === 0}
                                                onChange={() => {
                                                  setSelectedExpenses((prev) => {
                                                    const next = new Set(prev);
                                                    if (allPendingSelected) pendingInCenter.forEach((e) => next.delete(e.expense_id));
                                                    else pendingInCenter.forEach((e) => next.add(e.expense_id));
                                                    return next;
                                                  });
                                                }}
                                                className="h-4 w-4 rounded border-gray-300 text-primary-600 accent-primary-600 disabled:cursor-not-allowed disabled:opacity-40"
                                              />
                                            </th>
                                            <th className="px-5 py-3">Gasto</th>
                                            <th className="px-5 py-3">Fecha</th>
                                            <th className="px-5 py-3">Proveedor</th>
                                            <th className="px-5 py-3">Monto</th>
                                            <th className="px-5 py-3">Estado</th>
                                            <th className="px-5 py-3 text-center">Score</th>
                                          </tr>
                                        </thead>
                                        <tbody className="divide-y divide-gray-50">
                                          {row.expenses.map((expense) => {
                                            const isApproved = expense.review_status === "approved";
                                            const isRejected = expense.review_status === "rejected";
                                            const isPending = !isApproved && !isRejected;
                                            const docType = expense.document_type === "invoice" ? "Factura" : expense.document_type === "professional_fee_receipt" ? "Honorarios" : "Boleta";
                                            return (
                                              <tr key={expense.expense_id} className={`hover:bg-slate-50/60 ${selectedExpenses.has(expense.expense_id) ? "bg-primary-50/40" : ""}`}>
                                                <td className="px-3 py-3.5 align-top">
                                                  {isPending && (
                                                    <input
                                                      type="checkbox"
                                                      checked={selectedExpenses.has(expense.expense_id)}
                                                      onChange={() => toggleExpenseSelection(expense.expense_id)}
                                                      className="h-4 w-4 rounded border-gray-300 accent-primary-600"
                                                    />
                                                  )}
                                                </td>
                                                <td className="px-5 py-3.5 align-top">
                                                  <div className="flex items-start gap-3">
                                                    <Link href={`/expenses/${expense.expense_id}`} className="mt-0.5 flex-shrink-0">
                                                      {expense.image_url ? (
                                                        <img src={expense.image_url} alt="" className="h-9 w-9 rounded-lg border border-gray-200 object-cover" loading="lazy" />
                                                      ) : (
                                                        <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-gray-200 bg-gray-50 text-gray-400">
                                                          <FileText className="h-4 w-4" />
                                                        </span>
                                                      )}
                                                    </Link>
                                                    <div className="min-w-0">
                                                      <Link className="block text-sm font-semibold text-gray-900 hover:text-primary-700" href={`/expenses/${expense.expense_id}`}>
                                                        {expense.merchant || "Documento sin identificar"}
                                                      </Link>
                                                      {expense.category && <p className="text-xs text-gray-400">{expense.category}</p>}
                                                      <span className="mt-1 inline-flex rounded-md border border-primary-200 bg-primary-50 px-1.5 py-0.5 text-[10px] font-medium text-primary-700">
                                                        {docType}
                                                      </span>
                                                    </div>
                                                  </div>
                                                </td>
                                                <td className="px-5 py-3.5 align-top text-xs text-gray-500">{formatDateShort(expense.date)}</td>
                                                <td className="px-5 py-3.5 align-top">
                                                  <p className="text-sm font-medium text-gray-900">{expense.merchant || "-"}</p>
                                                  {(expense as any).rut && <p className="text-xs text-gray-400">{(expense as any).rut}</p>}
                                                </td>
                                                <td className="px-5 py-3.5 align-top">
                                                  <p className="text-sm font-semibold text-gray-900">
                                                    {expense.total_clp ? formatCLP(expense.total_clp) : `${expense.currency || ""} ${expense.total || "-"}`}
                                                  </p>
                                                  <p className="text-[10px] text-gray-400">Líquido</p>
                                                </td>
                                                <td className="px-5 py-3.5 align-top">
                                                  <div>
                                                    {isApproved ? (
                                                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                                                        <CheckCircle className="h-3 w-3" /> Aprobado
                                                      </span>
                                                    ) : isRejected ? (
                                                      <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
                                                        <XCircle className="h-3 w-3" /> Rechazado
                                                      </span>
                                                    ) : (
                                                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
                                                        <Clock className="h-3 w-3" /> Pendiente
                                                      </span>
                                                    )}
                                                  </div>
                                                  <div className="mt-2 flex items-start gap-1">
                                                    <Link href={`/expenses/${expense.expense_id}`} className="rounded-lg p-1.5 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700">
                                                      <Eye className="h-4 w-4" />
                                                    </Link>
                                                    {isPending && (
                                                      <div className="flex flex-col gap-1">
                                                        <button
                                                          className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700 transition hover:bg-emerald-100 disabled:opacity-50"
                                                          disabled={!!expenseActionLoading}
                                                          onClick={() => runExpenseAction(expense.expense_id, "approve")}
                                                          type="button"
                                                        >
                                                          <CheckCircle className="h-3 w-3" /> Aprobar
                                                        </button>
                                                        <button
                                                          className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-2 py-1 text-xs font-semibold text-red-700 transition hover:bg-red-100 disabled:opacity-50"
                                                          disabled={!!expenseActionLoading}
                                                          onClick={() => setRejectConfirm({ ids: [expense.expense_id] })}
                                                          type="button"
                                                        >
                                                          <XCircle className="h-3 w-3" /> Rechazar
                                                        </button>
                                                      </div>
                                                    )}
                                                  </div>
                                                </td>
                                                <td className="px-5 py-3.5 text-center align-top">
                                                  <ScoreBadge score={expense.review_score} />
                                                </td>
                                              </tr>
                                            );
                                          })}
                                        </tbody>
                                      </table>
                                    );
                                  })()}
                              </div>
                              <div className="border-t border-gray-100 px-5 py-3">
                                <button
                                  className="flex items-center gap-1.5 text-xs font-semibold text-primary-600 transition hover:text-primary-700"
                                  onClick={() => setExpandedCenters((prev) => ({ ...prev, [row.center]: false }))}
                                  type="button"
                                >
                                  <ChevronUp className="h-3.5 w-3.5" />
                                  Ocultar gastos de {row.center} ({row.count})
                                </button>
                              </div>
                            </div>
                          )}

                          {isExpanded && row.expenses.length === 0 && (
                            <div className="border-t border-gray-100 px-5 py-4 text-sm text-gray-400">
                              Aún no hay gastos en este centro de costo.
                            </div>
                          )}

                          {!isExpanded && row.expenses.length > 0 && (
                            <div className="border-t border-gray-100 px-5 py-3">
                              <button
                                className="flex items-center gap-1.5 text-xs font-semibold text-primary-600 transition hover:text-primary-700"
                                onClick={() => setExpandedCenters((prev) => ({ ...prev, [row.center]: true }))}
                                type="button"
                              >
                                <ChevronDown className="h-3.5 w-3.5" />
                                Ver todos los gastos de {row.center} ({row.count})
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* ── All expenses view ── */}
                {activeTab === "all" && (
                  <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
                    {expenses.length === 0 ? (
                      <p className="px-5 py-6 text-sm text-gray-500">Sin gastos registrados.</p>
                    ) : (
                      <>
                        {/* Mobile card list */}
                        <div className="sm:hidden">
                          <MobileExpenseList
                            expenses={expenses}
                            selectedExpenses={selectedExpenses}
                            expenseActionLoading={expenseActionLoading}
                            onToggleSelect={toggleExpenseSelection}
                            onApprove={(id) => runExpenseAction(id, "approve")}
                            onReject={(id) => setRejectConfirm({ ids: [id] })}
                            showCostCenter
                          />
                        </div>
                        {/* Desktop table */}
                        <div className="hidden overflow-x-auto sm:block">
                          {(() => {
                            const pendingAll = expenses.filter((e) => e.review_status !== "approved" && e.review_status !== "rejected");
                            const allPendingSelected = pendingAll.length > 0 && pendingAll.every((e) => selectedExpenses.has(e.expense_id));
                            return (
                              <table className="w-full min-w-[680px]">
                                <thead>
                                  <tr className="border-b border-gray-100 text-left text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-400">
                                    <th className="w-10 px-3 py-3">
                                      <input
                                        type="checkbox"
                                        checked={allPendingSelected}
                                        disabled={pendingAll.length === 0}
                                        onChange={() => {
                                          setSelectedExpenses((prev) => {
                                            const next = new Set(prev);
                                            if (allPendingSelected) pendingAll.forEach((e) => next.delete(e.expense_id));
                                            else pendingAll.forEach((e) => next.add(e.expense_id));
                                            return next;
                                          });
                                        }}
                                        className="h-4 w-4 rounded border-gray-300 accent-primary-600 disabled:cursor-not-allowed disabled:opacity-40"
                                      />
                                    </th>
                                    <th className="px-5 py-3">Gasto</th>
                                    <th className="px-5 py-3">Fecha</th>
                                    <th className="px-5 py-3">Centro de costo</th>
                                    <th className="px-5 py-3">Monto</th>
                                    <th className="px-5 py-3">Estado</th>
                                    <th className="px-5 py-3 text-center">Score</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-50">
                                  {expenses.map((expense) => {
                                    const isApproved = expense.review_status === "approved";
                                    const isRejected = expense.review_status === "rejected";
                                    const isPending = !isApproved && !isRejected;
                                    return (
                                      <tr key={expense.expense_id} className={`hover:bg-slate-50/60 ${selectedExpenses.has(expense.expense_id) ? "bg-primary-50/40" : ""}`}>
                                        <td className="px-3 py-3.5 align-top">
                                          {isPending && (
                                            <input
                                              type="checkbox"
                                              checked={selectedExpenses.has(expense.expense_id)}
                                              onChange={() => toggleExpenseSelection(expense.expense_id)}
                                              className="h-4 w-4 rounded border-gray-300 accent-primary-600"
                                            />
                                          )}
                                        </td>
                                        <td className="px-5 py-3.5 align-top">
                                          <div className="flex items-start gap-3">
                                            <Link href={`/expenses/${expense.expense_id}`} className="mt-0.5 flex-shrink-0">
                                              {expense.image_url ? (
                                                <img src={expense.image_url} alt="" className="h-9 w-9 rounded-lg border border-gray-200 object-cover" loading="lazy" />
                                              ) : (
                                                <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-gray-200 bg-gray-50 text-gray-400">
                                                  <FileText className="h-4 w-4" />
                                                </span>
                                              )}
                                            </Link>
                                            <div>
                                              <Link className="block text-sm font-semibold text-gray-900 hover:text-primary-700" href={`/expenses/${expense.expense_id}`}>
                                                {expense.merchant || "Documento sin identificar"}
                                              </Link>
                                              {expense.category && <p className="text-xs text-gray-400">{expense.category}</p>}
                                            </div>
                                          </div>
                                        </td>
                                        <td className="px-5 py-3.5 align-top text-xs text-gray-500">{formatDateShort(expense.date)}</td>
                                        <td className="px-5 py-3.5 align-top text-sm text-gray-500">{expense.cost_center || "-"}</td>
                                        <td className="px-5 py-3.5 align-top">
                                          <p className="text-sm font-semibold text-gray-900">
                                            {expense.total_clp ? formatCLP(expense.total_clp) : `${expense.currency || ""} ${expense.total || "-"}`}
                                          </p>
                                          <p className="text-[10px] text-gray-400">Líquido</p>
                                        </td>
                                        <td className="px-5 py-3.5 align-top">
                                          <div>
                                            {isApproved ? (
                                              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                                                <CheckCircle className="h-3 w-3" /> Aprobado
                                              </span>
                                            ) : isRejected ? (
                                              <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
                                                <XCircle className="h-3 w-3" /> Rechazado
                                              </span>
                                            ) : (
                                              <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
                                                <Clock className="h-3 w-3" /> Pendiente
                                              </span>
                                            )}
                                          </div>
                                          <div className="mt-2 flex items-start gap-1">
                                            <Link href={`/expenses/${expense.expense_id}`} className="rounded-lg p-1.5 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700">
                                              <Eye className="h-4 w-4" />
                                            </Link>
                                            {isPending && (
                                              <div className="flex flex-col gap-1">
                                                <button
                                                  className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700 transition hover:bg-emerald-100 disabled:opacity-50"
                                                  disabled={!!expenseActionLoading}
                                                  onClick={() => runExpenseAction(expense.expense_id, "approve")}
                                                  type="button"
                                                >
                                                  <CheckCircle className="h-3 w-3" /> Aprobar
                                                </button>
                                                <button
                                                  className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-2 py-1 text-xs font-semibold text-red-700 transition hover:bg-red-100 disabled:opacity-50"
                                                  disabled={!!expenseActionLoading}
                                                  onClick={() => setRejectConfirm({ ids: [expense.expense_id] })}
                                                  type="button"
                                                >
                                                  <XCircle className="h-3 w-3" /> Rechazar
                                                </button>
                                              </div>
                                            )}
                                          </div>
                                        </td>
                                        <td className="px-5 py-3.5 text-center align-top">
                                          <ScoreBadge score={expense.review_score} />
                                        </td>
                                      </tr>
                                    );
                                  })}
                                </tbody>
                              </table>
                            );
                          })()}
                        </div>
                      </>
                    )}
                    {fondos > 0 && (
                      <div className="border-t border-gray-100 px-5 py-3 text-xs text-gray-400">
                        Los montos mostrados son líquidos. Presupuesto total: {formatCLP(fondos)}.
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* ── Right sidebar ── */}
              <div className="space-y-6 xl:col-span-4">
                {/* Employee card */}
                <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
                  <h3 className="mb-4 text-sm font-semibold text-gray-900">Persona asociada</h3>
                  {employee ? (
                    <div className="space-y-3">
                      <div className="flex items-center gap-3">
                        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-100 text-sm font-semibold text-primary-700">
                          {employee.name?.charAt(0)?.toUpperCase() || "?"}
                        </div>
                        <div>
                          <p className="text-sm font-medium text-gray-900">{employee.name}</p>
                          <p className="font-mono text-xs text-gray-500">{employee.phone}</p>
                        </div>
                      </div>
                      <details className="group rounded-xl border border-gray-200 bg-gray-50">
                        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-medium text-gray-900">
                          <span>Ver más información</span>
                          <ChevronDown className="h-4 w-4 text-gray-500 transition group-open:rotate-180" />
                        </summary>
                        <div className="grid grid-cols-1 gap-3 border-t border-gray-200 bg-white p-4">
                          {(["company_id", "rut", "email", "bank_name", "account_type", "account_number", "account_holder", "account_holder_rut"] as const).map((field) => (
                            <div key={field} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                              <p className="text-[11px] font-medium uppercase tracking-wide text-gray-500">{employeeFieldLabels[field]}</p>
                              <p className="mt-1 text-sm text-gray-900">{employee[field] || "-"}</p>
                            </div>
                          ))}
                        </div>
                      </details>
                      <Link className="inline-flex items-center rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50" href={`/employees/${encodeURIComponent(employee.phone)}`}>
                        Ver persona
                      </Link>
                    </div>
                  ) : (
                    <p className="text-sm text-gray-500">Sin persona vinculada.</p>
                  )}
                </div>

                {/* Activity timeline */}
                {item && (
                  <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
                    <h3 className="mb-4 text-sm font-semibold text-gray-900">Historial de actividad</h3>
                    {(() => {
                      const events = buildTimeline(item, expenses);
                      if (events.length === 0) return <p className="text-sm text-gray-500">Sin actividad registrada.</p>;
                      return (
                        <div className="relative space-y-0">
                          {events.map((event, i) => {
                            const Icon = event.icon;
                            return (
                              <div key={i} className="relative flex gap-3 pb-5 last:pb-0">
                                {i < events.length - 1 && <div className="absolute left-[11px] top-6 h-full w-px bg-gray-200" />}
                                <div className="relative z-10 mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-white ring-2 ring-gray-100">
                                  <Icon className={`h-3.5 w-3.5 ${toneIcon[event.tone]}`} />
                                </div>
                                <div className="min-w-0">
                                  <p className="text-sm font-medium text-gray-900">{event.label}</p>
                                  {event.detail && <p className="truncate text-xs text-gray-500">{event.detail}</p>}
                                  <p className="mt-0.5 text-xs text-gray-400">{event.date.slice(0, 16).replace("T", " ")}</p>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      );
                    })()}
                  </div>
                )}

                {/* Chat */}
                {(item?.employee_phone || item?.phone) && (
                  <ChatPanel phone={item.employee_phone || item.phone || ""} maxHeight="min(72vh, 760px)" />
                )}
              </div>
            </div>
          </div>
        )}
      </Shell>
    </ProtectedPage>
  );
}
