"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle,
  ExternalLink,
  Eye,
  LoaderCircle,
  Pencil,
  RotateCcw,
  X,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/badge";
import { ProtectedPage } from "@/components/protected-page";
import { SectionCard } from "@/components/section-card";
import { Shell } from "@/components/shell";
import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api";
import { normalizeExpenseReviewFields } from "@/lib/expense-review";
import { useAutoRefresh } from "@/lib/use-auto-refresh";
import type { CaseItem, Employee, Expense } from "@/lib/types";

const fieldLabels: Record<string, string> = {
  merchant: "Comercio",
  date: "Fecha",
  currency: "Moneda",
  total: "Total",
  total_clp: "Total CLP",
  category: "Categoría",
  country: "País",
  status: "Estado",
};

const breakdownLabels: Record<string, string> = {
  document_quality: "Calidad documento",
  extraction_quality: "Calidad extracción",
  field_completeness: "Completitud campos",
  document_type_confidence: "Confianza tipo doc.",
  policy_risk: "Riesgo política",
  duplicate_risk: "Riesgo duplicado",
};

function ScoreBar({ score, label }: { score: number; label: string }) {
  let color = "bg-red-500";
  if (score >= 80) color = "bg-emerald-500";
  else if (score >= 50) color = "bg-amber-500";
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-600">{label}</span>
        <span className="font-semibold text-gray-900">{score}</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${Math.min(score, 100)}%` }}
        />
      </div>
    </div>
  );
}

function ReviewScoreRing({ score }: { score?: number }) {
  if (score == null)
    return (
      <div className="flex h-20 w-20 items-center justify-center rounded-full bg-gray-100 text-gray-400 text-sm">
        -
      </div>
    );
  let ring = "ring-red-300 text-red-700";
  if (score >= 80) ring = "ring-emerald-300 text-emerald-700";
  else if (score >= 50) ring = "ring-amber-300 text-amber-700";
  return (
    <div
      className={`flex h-20 w-20 items-center justify-center rounded-full bg-white ring-4 ${ring}`}
    >
      <span className="text-2xl font-bold">{score}</span>
    </div>
  );
}

export default function ExpenseDetailPage() {
  const params = useParams<{ expenseId: string }>();
  const { token } = useAuth();
  const expenseId = typeof params.expenseId === "string" ? params.expenseId : "";
  const [expense, setExpense] = useState<Expense | null>(null);
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [caseItem, setCaseItem] = useState<CaseItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [actionLoading, setActionLoading] = useState("");

  function fetchExpense() {
    if (!token || !expenseId) return;
    apiRequest<{ expense: Expense; employee: Employee; case: CaseItem }>(
      `/expenses/${expenseId}`,
      { token },
    ).then((data) => {
      setExpense(normalizeExpenseReviewFields(data.expense));
      setEmployee(data.employee);
      setCaseItem(data.case);
    });
  }

  useEffect(() => {
    fetchExpense();
  }, [expenseId, token]);

  useAutoRefresh(
    () => fetchExpense(),
    {
      enabled:
        Boolean(token) &&
        Boolean(expenseId) &&
        !isEditing &&
        !saving &&
        !actionLoading,
    },
  );

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !expense) return;
    setSaving(true);
    try {
      const form = new FormData(event.currentTarget);
      const updatedExpense = await apiRequest<Expense>(
        `/expenses/${expenseId}`,
        {
          method: "PUT",
          body: { ...expense, ...Object.fromEntries(form.entries()) },
          token,
        },
      );
      const normalizedExpense = normalizeExpenseReviewFields(updatedExpense);
      setExpense((current) => ({
        ...current,
        ...normalizedExpense,
        image_url: normalizedExpense.image_url || current?.image_url,
        document_url: normalizedExpense.document_url || current?.document_url,
      }));
      setIsEditing(false);
    } finally {
      setSaving(false);
    }
  }

  async function runAction(
    action: "approve" | "reject" | "observe" | "request_review",
  ) {
    if (!token) return;
    setActionLoading(action);
    try {
      await apiRequest(`/expenses/${expenseId}/actions`, {
        method: "POST",
        body: { action },
        token,
      });
      fetchExpense();
    } finally {
      setActionLoading("");
    }
  }

  const breakdown = expense?.review_breakdown;
  const flags = expense?.review_flags;

  return (
    <ProtectedPage>
      <Shell title="Detalle de gasto" description={expenseId}>
        {!expense && (
          <div
            className="mb-6 flex items-center gap-2 rounded-xl border border-primary-100 bg-white px-5 py-4 text-sm font-medium text-gray-700 shadow-sm"
            role="status"
            aria-live="polite"
          >
            <LoaderCircle className="h-4 w-4 animate-spin text-primary-600" />
            Cargando gasto...
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Main column */}
          <div className="space-y-6 lg:col-span-2">
            {/* Review score summary */}
            {expense && (
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <div className="flex items-start gap-6">
                  <ReviewScoreRing score={expense.review_score} />
                  <div className="flex-1">
                    <div className="mb-2 flex items-center gap-2">
                      <h3 className="text-sm font-semibold text-gray-900">
                        Puntaje de revisión
                      </h3>
                      <Badge>{expense.review_status || "-"}</Badge>
                      {expense.document_type && (
                        <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                          {expense.document_type}
                        </span>
                      )}
                    </div>
                    {flags && flags.length > 0 && (
                      <div className="mb-3 flex flex-wrap gap-1.5">
                        {flags.map((flag, i) => (
                          <span
                            key={i}
                            className="inline-flex items-center gap-1 rounded-full bg-orange-50 px-2.5 py-0.5 text-xs font-medium text-orange-700 ring-1 ring-inset ring-orange-600/20"
                          >
                            <AlertTriangle className="h-3 w-3" />
                            {flag}
                          </span>
                        ))}
                      </div>
                    )}
                    {/* Action buttons */}
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3.5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-50"
                        onClick={() => runAction("approve")}
                        disabled={
                          actionLoading === "approve" ||
                          expense.review_status === "approved"
                        }
                        type="button"
                      >
                        <CheckCircle className="h-4 w-4" />
                        {actionLoading === "approve"
                          ? "Aprobando..."
                          : "Aprobar"}
                      </button>
                      <button
                        className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3.5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-red-700 disabled:opacity-50"
                        onClick={() => runAction("reject")}
                        disabled={
                          actionLoading === "reject" ||
                          expense.review_status === "rejected"
                        }
                        type="button"
                      >
                        <XCircle className="h-4 w-4" />
                        {actionLoading === "reject"
                          ? "Rechazando..."
                          : "Rechazar"}
                      </button>
                      <button
                        className="inline-flex items-center gap-1.5 rounded-lg border border-purple-300 px-3.5 py-2 text-sm font-semibold text-purple-700 transition hover:bg-purple-50 disabled:opacity-50"
                        onClick={() => runAction("observe")}
                        disabled={
                          actionLoading === "observe" ||
                          expense.review_status === "observed"
                        }
                        type="button"
                      >
                        <Eye className="h-4 w-4" />
                        {actionLoading === "observe"
                          ? "Observando..."
                          : "Observar"}
                      </button>
                      <button
                        className="inline-flex items-center gap-1.5 rounded-lg border border-orange-300 px-3.5 py-2 text-sm font-semibold text-orange-700 transition hover:bg-orange-50 disabled:opacity-50"
                        onClick={() => runAction("request_review")}
                        disabled={
                          actionLoading === "request_review" ||
                          expense.review_status === "needs_manual_review"
                        }
                        type="button"
                      >
                        <RotateCcw className="h-4 w-4" />
                        Solicitar revisión
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Review breakdown */}
            {breakdown && (
              <SectionCard title="Desglose de revisión">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {Object.entries(breakdownLabels).map(([key, label]) => (
                    <ScoreBar
                      key={key}
                      label={label}
                      score={breakdown[key] ?? 0}
                    />
                  ))}
                </div>
              </SectionCard>
            )}

            {/* Receipt image */}
            <SectionCard title="Comprobante">
              {expense?.image_url ? (
                <a
                  href={expense.image_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  <img
                    alt={`Boleta ${expense.expense_id}`}
                    className="max-h-[36rem] w-full rounded-xl border border-gray-200 bg-white object-contain"
                    src={expense.image_url}
                  />
                </a>
              ) : expense?.document_url ? (
                <div className="space-y-4">
                  <iframe
                    className="h-[36rem] w-full rounded-xl border border-gray-200 bg-white"
                    src={expense.document_url}
                    title={`Boleta ${expense.expense_id}`}
                  />
                  <a
                    className="inline-flex items-center gap-2 text-sm font-medium text-primary-600 transition hover:text-primary-700"
                    href={expense.document_url}
                    rel="noreferrer"
                    target="_blank"
                  >
                    <ExternalLink className="h-4 w-4" />
                    Abrir comprobante en nueva pestaña
                  </a>
                </div>
              ) : (
                <p className="text-sm text-gray-500">
                  No hay comprobante disponible para este gasto.
                </p>
              )}
            </SectionCard>

            {/* Extracted fields */}
            <SectionCard
              title="Campos extraídos"
              action={
                expense ? (
                  <button
                    className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition ${
                      isEditing
                        ? "border border-gray-200 text-gray-600 hover:bg-gray-50"
                        : "bg-primary-600 text-white hover:bg-primary-700"
                    }`}
                    onClick={() => setIsEditing((v) => !v)}
                    type="button"
                  >
                    {isEditing ? (
                      <>
                        <X className="h-4 w-4" />
                        Cerrar edición
                      </>
                    ) : (
                      <>
                        <Pencil className="h-4 w-4" />
                        Editar gasto
                      </>
                    )}
                  </button>
                ) : null
              }
            >
              {expense ? (
                isEditing ? (
                  <form className="space-y-4" onSubmit={onSubmit}>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      {(
                        [
                          "merchant",
                          "date",
                          "currency",
                          "total",
                          "total_clp",
                          "category",
                          "country",
                          "status",
                        ] as const
                      ).map((field) => (
                        <div key={field}>
                          <label className="mb-1.5 block text-sm font-medium text-gray-700">
                            {fieldLabels[field]}
                          </label>
                          <input
                            defaultValue={String(
                              expense[field as keyof Expense] || "",
                            )}
                            name={field}
                            className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                          />
                        </div>
                      ))}
                    </div>
                    <button
                      className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700 disabled:opacity-50"
                      type="submit"
                      disabled={saving}
                    >
                      {saving ? "Guardando..." : "Guardar cambios"}
                    </button>
                  </form>
                ) : (
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    {(
                      [
                        "merchant",
                        "date",
                        "currency",
                        "total",
                        "total_clp",
                        "category",
                        "country",
                        "status",
                      ] as const
                    ).map((field) => (
                      <div
                        key={field}
                        className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3"
                      >
                        <p className="mb-1 text-xs font-medium uppercase tracking-wide text-gray-500">
                          {fieldLabels[field]}
                        </p>
                        <p className="text-sm text-gray-900">
                          {String(expense[field as keyof Expense] || "-")}
                        </p>
                      </div>
                    ))}
                  </div>
                )
              ) : (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <div key={i}>
                      <div className="skeleton mb-1.5 h-4 w-20" />
                      <div className="skeleton h-9 w-full rounded-lg" />
                    </div>
                  ))}
                </div>
              )}
            </SectionCard>
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            <SectionCard title="Vínculos operativos">
              <div className="space-y-3">
                {employee && (
                  <Link
                    className="flex items-center gap-3 rounded-lg border border-gray-200 p-3 transition hover:bg-gray-50"
                    href={`/employees/${encodeURIComponent(employee.phone)}`}
                  >
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary-100 text-sm font-semibold text-primary-700">
                      {employee.name?.charAt(0)?.toUpperCase() || "?"}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-gray-900">
                        {employee.name}
                      </p>
                      <p className="text-xs text-gray-500">Persona</p>
                    </div>
                  </Link>
                )}
                {caseItem && (
                  <Link
                    className="flex items-center gap-3 rounded-lg border border-gray-200 p-3 transition hover:bg-gray-50"
                    href={`/cases/${caseItem.case_id}`}
                  >
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-100 text-sm font-semibold text-blue-700">
                      C
                    </div>
                    <div>
                      <p className="font-mono text-sm font-medium text-gray-900">
                        {caseItem.case_id}
                      </p>
                      <p className="text-xs text-gray-500">Caso</p>
                    </div>
                  </Link>
                )}
                {expense?.image_url && (
                  <a
                    className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                    href={expense.image_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ExternalLink className="h-4 w-4 text-gray-400" />
                    Abrir imagen
                  </a>
                )}
                {expense?.document_url && (
                  <a
                    className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                    href={expense.document_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ExternalLink className="h-4 w-4 text-gray-400" />
                    Abrir documento
                  </a>
                )}
                {!employee &&
                  !caseItem &&
                  !expense?.image_url &&
                  !expense?.document_url && (
                    <p className="text-sm text-gray-500">
                      Sin vínculos disponibles.
                    </p>
                  )}
              </div>
            </SectionCard>
          </div>
        </div>
      </Shell>
    </ProtectedPage>
  );
}
