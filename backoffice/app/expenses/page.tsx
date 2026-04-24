"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle,
  CheckSquare,
  Download,
  Ellipsis,
  Filter,
  Search,
  Square,
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
import { normalizeExpenseReviewFields } from "@/lib/expense-review";
import { useAutoRefresh } from "@/lib/use-auto-refresh";
import type { Expense } from "@/lib/types";

const filterLabels: Record<string, string> = {
  status: "Estado",
  review_status: "Estado revisión",
  employee_phone: "Teléfono empleado",
  category: "Categoría",
  date_from: "Fecha desde",
  date_to: "Fecha hasta",
};

const reviewStatusLabels: Record<string, string> = {
  needs_manual_review: "Requiere revisión manual",
  pending_review: "Pendiente de revisión",
  ready_to_approve: "Listo para aprobar",
  observed: "Observado",
  approved: "Aprobado",
  rejected: "Rechazado",
};

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

type FilterState = {
  status: string;
  review_status: string;
  employee_phone: string;
  category: string;
  date_from: string;
  date_to: string;
};

const emptyFilters: FilterState = {
  status: "",
  review_status: "",
  employee_phone: "",
  category: "",
  date_from: "",
  date_to: "",
};

type BatchConfirm = {
  action: "approve" | "reject";
  ids: string[];
} | null;

function renderSecondaryExpenseAction({
  label,
  tone,
  onClick,
}: {
  label: string;
  tone: "danger" | "accent";
  onClick: () => void;
}) {
  const className =
    tone === "danger"
      ? "text-red-600 hover:bg-red-50"
      : "text-purple-600 hover:bg-purple-50";

  return (
    <button
      className={`block w-full rounded-md px-3 py-2 text-left text-xs font-medium transition ${className}`}
      onClick={(event) => {
        (event.currentTarget.closest("details") as HTMLDetailsElement | null)?.removeAttribute("open");
        onClick();
      }}
      type="button"
    >
      {label}
    </button>
  );
}

export default function ExpensesPage() {
  const { token } = useAuth();
  const [items, setItems] = useState<Expense[] | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState<FilterState>({ ...emptyFilters });
  const [quickFilter, setQuickFilter] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchConfirm, setBatchConfirm] = useState<BatchConfirm>(null);
  const [batchLoading, setBatchLoading] = useState(false);

  async function exportCsv() {
    if (!token) return;
    const response = await fetch(`${getApiBaseUrl()}/expenses/export/csv`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "gastos.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  function load(nextFilters = filters) {
    if (!token) return;
    setSelected(new Set());
    const params: Record<string, string> = {};
    for (const [key, value] of Object.entries(nextFilters)) {
      if (value) params[key] = value;
    }
    const query = new URLSearchParams(params).toString();
    apiRequest<{ items: Expense[] }>(`/expenses${query ? `?${query}` : ""}`, {
      token,
    }).then((data) =>
      setItems(data.items.map((expense) => normalizeExpenseReviewFields(expense))),
    );
  }

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const nextFilters: FilterState = {
      status: params.get("status") || "",
      review_status: params.get("review_status") || "",
      employee_phone: params.get("employee_phone") || "",
      category: params.get("category") || "",
      date_from: params.get("date_from") || "",
      date_to: params.get("date_to") || "",
    };
    setFilters(nextFilters);
    const qf = params.get("review_status") || "";
    if (qf) setQuickFilter(qf);
    load(nextFilters);
  }, [token]);

  useAutoRefresh(
    () => load(),
    { enabled: Boolean(token) && !batchLoading && !batchConfirm },
  );

  function applyQuickFilter(value: string) {
    const next = { ...emptyFilters, review_status: value === quickFilter ? "" : value };
    setQuickFilter(next.review_status);
    setFilters(next);
    load(next);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setQuickFilter(filters.review_status);
    load();
  }

  async function runAction(
    expenseId: string,
    action: "approve" | "reject" | "observe" | "request_review",
  ) {
    if (!token) return;
    await apiRequest(`/expenses/${expenseId}/actions`, {
      method: "POST",
      body: { action },
      token,
    });
    load();
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    if (!items) return;
    const actionable = items.filter(
      (e) => e.review_status !== "approved" && e.review_status !== "rejected",
    );
    if (selected.size === actionable.length && actionable.length > 0) {
      setSelected(new Set());
    } else {
      setSelected(new Set(actionable.map((e) => e.expense_id)));
    }
  }

  async function executeBatch(action: "approve" | "reject", ids: string[]) {
    if (!token || ids.length === 0) return;
    setBatchLoading(true);
    try {
      await Promise.all(
        ids.map((id) =>
          apiRequest(`/expenses/${id}/actions`, {
            method: "POST",
            body: { action },
            token,
          }),
        ),
      );
    } finally {
      setBatchLoading(false);
      setBatchConfirm(null);
      setSelected(new Set());
      load();
    }
  }

  const counts = items
    ? {
        needs_manual_review: items.filter(
          (e) => e.review_status === "needs_manual_review",
        ).length,
        pending_review: items.filter(
          (e) => e.review_status === "pending_review",
        ).length,
        ready_to_approve: items.filter(
          (e) => e.review_status === "ready_to_approve",
        ).length,
      }
    : null;

  return (
    <ProtectedPage>
      <Shell
        title="Gastos"
        description="Revisión y aprobación de gastos con priorización automática."
      >
        {/* Quick filter buttons */}
        {counts && (
          <div className="mb-5 flex flex-wrap items-center gap-2">
            <button
              onClick={() => applyQuickFilter("needs_manual_review")}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition ${
                quickFilter === "needs_manual_review"
                  ? "border-orange-300 bg-orange-50 text-orange-700"
                  : "border-gray-200 text-gray-600 hover:bg-gray-50"
              }`}
              type="button"
            >
              <AlertTriangle className="h-3.5 w-3.5" />
              Revisión manual
              <span className="ml-0.5 rounded-full bg-orange-100 px-1.5 text-xs font-bold text-orange-700">
                {counts.needs_manual_review}
              </span>
            </button>
            <button
              onClick={() => applyQuickFilter("pending_review")}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition ${
                quickFilter === "pending_review"
                  ? "border-amber-300 bg-amber-50 text-amber-700"
                  : "border-gray-200 text-gray-600 hover:bg-gray-50"
              }`}
              type="button"
            >
              <Search className="h-3.5 w-3.5" />
              Pendiente
              <span className="ml-0.5 rounded-full bg-amber-100 px-1.5 text-xs font-bold text-amber-700">
                {counts.pending_review}
              </span>
            </button>
            <button
              onClick={() => applyQuickFilter("ready_to_approve")}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition ${
                quickFilter === "ready_to_approve"
                  ? "border-emerald-300 bg-emerald-50 text-emerald-700"
                  : "border-gray-200 text-gray-600 hover:bg-gray-50"
              }`}
              type="button"
            >
              <CheckCircle className="h-3.5 w-3.5" />
              Listos
              <span className="ml-0.5 rounded-full bg-emerald-100 px-1.5 text-xs font-bold text-emerald-700">
                {counts.ready_to_approve}
              </span>
            </button>
            {quickFilter && (
              <button
                onClick={() => applyQuickFilter(quickFilter)}
                className="text-xs text-gray-500 underline hover:text-gray-700"
                type="button"
              >
                Limpiar filtro
              </button>
            )}
          </div>
        )}

        {/* Advanced filters */}
        <div className="mb-6 flex items-center gap-3">
          <button
            className="flex items-center gap-2 rounded-lg border border-gray-300 px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            onClick={() => setFiltersOpen(!filtersOpen)}
            type="button"
          >
            <Filter className="h-4 w-4" />
            Filtros avanzados
            {Object.values(filters).some(Boolean) && (
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary-100 text-xs font-semibold text-primary-700">
                {Object.values(filters).filter(Boolean).length}
              </span>
            )}
          </button>
          <button
            onClick={() => {
              void exportCsv();
            }}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            type="button"
          >
            <Download className="h-4 w-4" />
            Exportar CSV
          </button>
        </div>

          {filtersOpen && (
            <div className="mb-6 rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
              <form onSubmit={onSubmit}>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {(Object.keys(filters) as (keyof FilterState)[]).map(
                    (field) => (
                      <div key={field}>
                        <label className="mb-1.5 block text-sm font-medium text-gray-700">
                          {filterLabels[field]}
                        </label>
                        {field === "review_status" ? (
                          <select
                            value={filters.review_status}
                            onChange={(e) =>
                              setFilters((c) => ({
                                ...c,
                                review_status: e.target.value,
                              }))
                            }
                            className="block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                          >
                            <option value="">Todos</option>
                            {Object.entries(reviewStatusLabels).map(
                              ([value, label]) => (
                                <option key={value} value={value}>
                                  {label}
                                </option>
                              ),
                            )}
                          </select>
                        ) : (
                          <input
                            value={filters[field]}
                            onChange={(e) =>
                              setFilters((c) => ({
                                ...c,
                                [field]: e.target.value,
                              }))
                            }
                            className="block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                          />
                        )}
                      </div>
                    ),
                  )}
                </div>
                <div className="mt-4 flex items-center gap-2">
                  <button
                    className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700"
                    type="submit"
                  >
                    Aplicar filtros
                  </button>
                  <button
                    className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                    onClick={() => {
                      setFilters({ ...emptyFilters });
                      setQuickFilter("");
                    }}
                    type="button"
                  >
                    Limpiar
                  </button>
                </div>
              </form>
            </div>
          )}

        {/* Batch action bar */}
        {selected.size > 0 && (
          <div className="mb-4 flex items-center gap-3 rounded-xl border border-primary-200 bg-primary-50 px-4 py-3">
            <span className="text-sm font-medium text-primary-800">
              {selected.size} documento{selected.size > 1 ? "s" : ""} seleccionado{selected.size > 1 ? "s" : ""}
            </span>
            <div className="flex items-center gap-2">
              <button
                className="rounded-lg bg-emerald-600 px-3.5 py-1.5 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700"
                onClick={() =>
                  setBatchConfirm({ action: "approve", ids: [...selected] })
                }
                type="button"
              >
                Aprobar seleccionados
              </button>
              <button
                className="rounded-lg bg-red-600 px-3.5 py-1.5 text-sm font-semibold text-white shadow-sm transition hover:bg-red-700"
                onClick={() =>
                  setBatchConfirm({ action: "reject", ids: [...selected] })
                }
                type="button"
              >
                Rechazar seleccionados
              </button>
            </div>
            <button
              className="ml-auto text-sm text-gray-500 transition hover:text-gray-700"
              onClick={() => setSelected(new Set())}
              type="button"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* Batch confirmation dialog */}
        {batchConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
            <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
              <h3 className="text-lg font-semibold text-gray-900">
                Confirmar acción masiva
              </h3>
              <p className="mt-2 text-sm text-gray-600">
                {batchConfirm.action === "approve"
                  ? `Vas a aprobar ${batchConfirm.ids.length} documento${batchConfirm.ids.length > 1 ? "s" : ""}. Se notificará a cada empleado por WhatsApp.`
                  : `Vas a rechazar ${batchConfirm.ids.length} documento${batchConfirm.ids.length > 1 ? "s" : ""}. Se notificará a cada empleado por WhatsApp.`}
              </p>
              <div className="mt-5 flex items-center justify-end gap-3">
                <button
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                  onClick={() => setBatchConfirm(null)}
                  disabled={batchLoading}
                  type="button"
                >
                  Cancelar
                </button>
                <button
                  className={`rounded-lg px-4 py-2 text-sm font-semibold text-white shadow-sm transition ${
                    batchConfirm.action === "approve"
                      ? "bg-emerald-600 hover:bg-emerald-700"
                      : "bg-red-600 hover:bg-red-700"
                  }`}
                  onClick={() =>
                    executeBatch(batchConfirm.action, batchConfirm.ids)
                  }
                  disabled={batchLoading}
                  type="button"
                >
                  {batchLoading
                    ? "Procesando..."
                    : batchConfirm.action === "approve"
                      ? "Confirmar aprobación"
                      : "Confirmar rechazo"}
                </button>
              </div>
            </div>
          </div>
        )}

        <SectionCard title="Listado de gastos">
          {items === null ? (
            <TableSkeleton columns={5} rows={6} />
          ) : (
            <DataTable
              columns={[
                <button
                  key="select-all"
                  type="button"
                  onClick={toggleSelectAll}
                  className="flex items-center"
                >
                  {items.length > 0 &&
                  selected.size ===
                    items.filter(
                      (e) =>
                        e.review_status !== "approved" &&
                        e.review_status !== "rejected",
                    ).length &&
                  selected.size > 0 ? (
                    <CheckSquare className="h-4 w-4 text-primary-600" />
                  ) : (
                    <Square className="h-4 w-4 text-gray-400" />
                  )}
                </button>,
                "Empleado",
                "Boleta",
                "Monto",
                "Score",
              ]}
              rowHrefs={items.map((expense) => `/expenses/${expense.expense_id}`)}
              rows={items.map((expense) => {
                const actionable =
                  expense.review_status !== "approved" &&
                  expense.review_status !== "rejected";
                const canApprove = expense.review_status !== "approved";
                const canReject = expense.review_status !== "rejected";
                const canObserve = expense.review_status !== "observed";
                return [
                  <button
                    key="check"
                    type="button"
                    onClick={() => actionable && toggleSelect(expense.expense_id)}
                    className={`flex items-center ${actionable ? "cursor-pointer" : "cursor-default opacity-30"}`}
                  >
                    {selected.has(expense.expense_id) ? (
                      <CheckSquare className="h-4 w-4 text-primary-600" />
                    ) : (
                      <Square className="h-4 w-4 text-gray-400" />
                    )}
                  </button>,
                  <div
                    key="emp"
                    className="min-w-[190px]"
                  >
                    <span className="block font-medium text-gray-900">
                      {expense.employee?.name ||
                        expense.case?.employee?.name ||
                        expense.phone}
                    </span>
                    <span className="mt-1 block text-xs text-gray-500">
                      {expense.phone}
                    </span>
                  </div>,
                  <div key="document" className="min-w-[280px]">
                    <span className="block font-medium text-gray-900">
                      {expense.merchant || "Comercio sin identificar"}
                    </span>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                      <span>{expense.date || "Sin fecha"}</span>
                      <Badge tone={expense.review_status || expense.status || undefined}>
                        {reviewStatusLabels[expense.review_status || ""] ||
                          expense.review_status ||
                          expense.status ||
                          "-"}
                      </Badge>
                    </div>
                    <div className="mt-3 flex items-center gap-2 opacity-80 transition group-hover:opacity-100 group-focus-within:opacity-100">
                      {canApprove && (
                        <button
                          className="rounded-md bg-emerald-600 px-2.5 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:bg-emerald-700"
                          onClick={() => runAction(expense.expense_id, "approve")}
                          type="button"
                        >
                          Aprobar
                        </button>
                      )}
                      {(canReject || canObserve) && (
                        <details className="relative">
                          <summary className="flex h-8 w-8 cursor-pointer list-none items-center justify-center rounded-md border border-gray-300 bg-white text-gray-600 transition hover:bg-gray-50 [&::-webkit-details-marker]:hidden">
                            <Ellipsis className="h-4 w-4" />
                          </summary>
                          <div className="absolute left-0 top-10 z-10 min-w-[150px] rounded-xl border border-gray-200 bg-white p-1 shadow-lg">
                            {canReject &&
                              renderSecondaryExpenseAction({
                                label: "Rechazar",
                                tone: "danger",
                                onClick: () => runAction(expense.expense_id, "reject"),
                              })}
                            {canObserve &&
                              renderSecondaryExpenseAction({
                                label: "Observar",
                                tone: "accent",
                                onClick: () => runAction(expense.expense_id, "observe"),
                              })}
                          </div>
                        </details>
                      )}
                    </div>
                  </div>,
                  <div key="amount" className="min-w-[130px]">
                    <span className="block text-sm font-semibold text-gray-900">
                      {`${expense.currency || ""} ${expense.total || "-"}`}
                    </span>
                    <span className="mt-1 block text-xs text-gray-500">
                      {expense.total_clp ? `${Number(expense.total_clp).toLocaleString("es-CL")} CLP` : ""}
                    </span>
                  </div>,
                  <ReviewScoreBadge
                    key="score"
                    score={expense.review_score}
                  />,
                ];
              })}
            />
          )}
        </SectionCard>
      </Shell>
    </ProtectedPage>
  );
}
