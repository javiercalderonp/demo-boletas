"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Banknote,
  CheckCircle,
  ChevronDown,
  FileSearch,
  FolderOpen,
  MessageSquare,
  XCircle,
} from "lucide-react";

import { DataTable } from "@/components/data-table";
import { ProtectedPage } from "@/components/protected-page";
import { SectionCard } from "@/components/section-card";
import { Shell } from "@/components/shell";
import { StatCard, StatCardSkeleton } from "@/components/stat-card";
import { Badge } from "@/components/badge";
import { TableSkeleton } from "@/components/table-skeleton";
import { apiRequest } from "@/lib/api";
import { useAutoRefresh } from "@/lib/use-auto-refresh";
import type { DashboardData } from "@/lib/types";
import { useAuth } from "@/components/auth-provider";

function formatCLP(value?: number): string {
  if (value == null || isNaN(value)) return "-";
  return `$${value.toLocaleString("es-CL", { maximumFractionDigits: 0 })}`;
}

const statusColors: Record<string, string> = {
  open: "#3b82f6",
  pending_user_confirmation: "#f59e0b",
  approved: "#10b981",
  closed: "#6b7280",
};

const statusLabels: Record<string, string> = {
  open: "Abiertas",
  pending_user_confirmation: "Esperando confirmación",
  approved: "Aprobadas",
  closed: "Cerradas",
};

function DonutChart({ distribution }: { distribution: Record<string, number> }) {
  const entries = Object.entries(distribution).filter(([, v]) => v > 0);
  const total = entries.reduce((sum, [, v]) => sum + v, 0);
  if (total === 0) return <p className="text-sm text-gray-500">Sin rendiciones.</p>;

  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  return (
    <div className="flex items-center gap-6">
      <svg width="120" height="120" viewBox="0 0 100 100" className="flex-shrink-0">
        {entries.map(([status, count]) => {
          const pct = count / total;
          const dashLength = pct * circumference;
          const segment = (
            <circle
              key={status}
              cx="50"
              cy="50"
              r={radius}
              fill="none"
              stroke={statusColors[status] || "#9ca3af"}
              strokeWidth="16"
              strokeDasharray={`${dashLength} ${circumference - dashLength}`}
              strokeDashoffset={-offset}
              transform="rotate(-90 50 50)"
            />
          );
          offset += dashLength;
          return segment;
        })}
        <text x="50" y="47" textAnchor="middle" className="text-lg font-bold" fill="#111827" fontSize="18">
          {total}
        </text>
        <text x="50" y="62" textAnchor="middle" fill="#6b7280" fontSize="8">
          rendiciones
        </text>
      </svg>
      <div className="space-y-1.5">
        {entries.map(([status, count]) => (
          <div key={status} className="flex items-center gap-2">
            <span
              className="h-2.5 w-2.5 flex-shrink-0 rounded-full"
              style={{ backgroundColor: statusColors[status] || "#9ca3af" }}
            />
            <span className="text-xs text-gray-600">
              {statusLabels[status] || status}
            </span>
            <span className="text-xs font-semibold text-gray-900">{count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const severityStyles: Record<string, string> = {
  error:
    "bg-red-50 border-red-200 text-red-800",
  warning:
    "bg-amber-50 border-amber-200 text-amber-800",
};

const severityDot: Record<string, string> = {
  error: "bg-red-500",
  warning: "bg-amber-500",
};

const severityLabel: Record<string, string> = {
  error: "crítica",
  warning: "pendiente",
};

const dashboardStatLinks = {
  totalFondos: "/cases",
  totalRendido: "/expenses?review_status=approved",
  totalPendienteRevision: "/expenses?review_status=pending_review",
  totalSaldo: "/cases",
  rendicionesAbiertas: "/cases?status=open",
  rendicionesPendientes: "/cases?status=pending_user_confirmation",
  docsPorRevisar: "/expenses?review_status=needs_manual_review",
  conversaciones: "/conversations?state=active",
};

export default function DashboardPage() {
  const { token } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;
    apiRequest<DashboardData>("/dashboard", { token })
      .then(setData)
      .catch((nextError) => setError(nextError.message));
  }, [token]);

  useAutoRefresh(
    () => {
      if (!token) return;
      return apiRequest<DashboardData>("/dashboard", { token })
        .then(setData)
        .catch((nextError) => setError(nextError.message));
    },
    { enabled: Boolean(token) },
  );

  return (
    <ProtectedPage>
      <Shell
        title="Dashboard"
        description="Resumen operativo de rendiciones y fondos por rendir."
      >
        {error && (
          <div className="mb-6 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Primary stats */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {data ? (
            <>
              <Link href={dashboardStatLinks.totalFondos} className="group block">
                <StatCard
                  label="Fondos entregados"
                  value={formatCLP(data.stats.total_fondos)}
                  icon={Banknote}
                  className="transition group-hover:border-primary-300 group-hover:shadow-md"
                />
              </Link>
              <Link href={dashboardStatLinks.totalRendido} className="group block">
                <StatCard
                  label="Total rendido"
                  value={formatCLP(data.stats.total_rendido_aprobado)}
                  icon={CheckCircle}
                  tone="success"
                  className="transition group-hover:border-emerald-300 group-hover:shadow-md"
                />
              </Link>
              <Link href={dashboardStatLinks.totalPendienteRevision} className="group block">
                <StatCard
                  label="Pendiente revisión"
                  value={formatCLP(data.stats.total_pendiente_revision)}
                  icon={FileSearch}
                  tone={data.stats.total_pendiente_revision > 0 ? "warning" : "default"}
                  className="transition group-hover:border-amber-300 group-hover:shadow-md"
                />
              </Link>
              <Link href={dashboardStatLinks.totalSaldo} className="group block">
                <StatCard
                  label="Saldo total"
                  value={formatCLP(data.stats.total_saldo)}
                  icon={Banknote}
                  tone={data.stats.total_saldo < 0 ? "error" : "default"}
                  className="transition group-hover:border-primary-300 group-hover:shadow-md"
                />
              </Link>
            </>
          ) : (
            <>
              <StatCardSkeleton />
              <StatCardSkeleton />
              <StatCardSkeleton />
              <StatCardSkeleton />
            </>
          )}
        </div>

        {/* Secondary stats */}
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {data ? (
            <>
              <Link href={dashboardStatLinks.rendicionesAbiertas} className="group block">
                <StatCard
                  label="Rendiciones abiertas"
                  value={data.stats.rendiciones_open}
                  icon={FolderOpen}
                  className="transition group-hover:border-blue-300 group-hover:shadow-md"
                />
              </Link>
              <Link href={dashboardStatLinks.rendicionesPendientes} className="group block">
                <StatCard
                  label="En revisión"
                  value={data.stats.rendiciones_pending}
                  icon={FileSearch}
                  tone={data.stats.rendiciones_pending > 0 ? "warning" : "default"}
                  className="transition group-hover:border-amber-300 group-hover:shadow-md"
                />
              </Link>
              <Link href={dashboardStatLinks.docsPorRevisar} className="group block">
                <StatCard
                  label="Docs por revisar"
                  value={data.stats.docs_needs_review}
                  icon={AlertTriangle}
                  tone={data.stats.docs_needs_review > 0 ? "warning" : "default"}
                  className="transition group-hover:border-orange-300 group-hover:shadow-md"
                />
              </Link>
              <Link href={dashboardStatLinks.conversaciones} className="group block">
                <StatCard
                  label="Conversaciones"
                  value={data.stats.active_conversations}
                  icon={MessageSquare}
                  className="transition group-hover:border-primary-300 group-hover:shadow-md"
                />
              </Link>
            </>
          ) : (
            <>
              <StatCardSkeleton />
              <StatCardSkeleton />
              <StatCardSkeleton />
              <StatCardSkeleton />
            </>
          )}
        </div>

        {/* Chart + Rendiciones */}
        <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-5">
          <div className="xl:col-span-2">
            <SectionCard title="Estado de rendiciones">
              {data?.rendicion_status_distribution ? (
                <DonutChart distribution={data.rendicion_status_distribution} />
              ) : (
                <div className="flex items-center justify-center py-8">
                  <div className="skeleton h-[120px] w-[120px] rounded-full" />
                </div>
              )}
            </SectionCard>
          </div>

          <div className="xl:col-span-3">
          <SectionCard
            title="Rendiciones activas"
            action={
              <Link
                href="/cases"
                className="flex items-center gap-1 text-xs font-medium text-primary-600 transition hover:text-primary-700"
              >
                Ver todas <ArrowRight className="h-3 w-3" />
              </Link>
            }
          >
            {data ? (
              <DataTable
                columns={[
                  "Rendición",
                  "Empleado",
                  "Fondos",
                  "Aprobado",
                  "Saldo",
                  "Estado",
                  "",
                ]}
                rows={(data.rendiciones || []).map((c) => [
                  <span key="id" className="font-mono text-xs">
                    {c.case_id}
                  </span>,
                  <span key="emp" className="text-sm">
                    {c.employee?.name || c.employee_phone || "-"}
                  </span>,
                  <span key="fondos" className="text-sm font-medium">
                    {formatCLP(
                      typeof c.fondos_entregados === "string"
                        ? parseFloat(c.fondos_entregados) || 0
                        : (c.fondos_entregados as number) || 0,
                    )}
                  </span>,
                  <span
                    key="aprobado"
                    className="text-sm text-emerald-700"
                  >
                    {formatCLP(c.monto_rendido_aprobado)}
                  </span>,
                  <span
                    key="saldo"
                    className={`text-sm font-medium ${(c.saldo_restante ?? 0) < 0 ? "text-red-600" : "text-gray-900"}`}
                  >
                    {formatCLP(c.saldo_restante)}
                  </span>,
                  <Badge key="status">
                    {c.rendicion_status || c.status}
                  </Badge>,
                  <Link
                    key="link"
                    className="text-sm font-medium text-primary-600 transition hover:text-primary-700"
                    href={`/cases/${c.case_id}`}
                  >
                    Ver
                  </Link>,
                ])}
              />
            ) : (
              <TableSkeleton columns={7} rows={4} />
            )}
          </SectionCard>
          </div>
        </div>

        {/* Tables */}
        <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-5">
          <div className="xl:col-span-3">
            <SectionCard
              title="Últimos documentos"
              action={
                <Link
                  href="/expenses"
                  className="flex items-center gap-1 text-xs font-medium text-primary-600 transition hover:text-primary-700"
                >
                  Ver todos <ArrowRight className="h-3 w-3" />
                </Link>
              }
            >
              {data ? (
                <DataTable
                  columns={["Doc", "Empleado", "Merchant", "Monto", "Review", ""]}
                  rows={(data.latest_expenses || []).map((expense) => [
                    <span key="id" className="font-mono text-xs">
                      {expense.expense_id}
                    </span>,
                    <span key="emp" className="text-sm">
                      {expense.employee?.name || expense.phone}
                    </span>,
                    <span key="merchant" className="text-sm">
                      {expense.merchant || "-"}
                    </span>,
                    <span key="amount" className="text-sm font-medium">
                      {`${expense.currency || ""} ${expense.total || "-"}`}
                    </span>,
                    <Badge key="status">
                      {expense.review_status || expense.status || "-"}
                    </Badge>,
                    <Link
                      className="text-sm font-medium text-primary-600 transition hover:text-primary-700"
                      href={`/expenses/${expense.expense_id}`}
                      key="view"
                    >
                      Ver
                    </Link>,
                  ])}
                />
              ) : (
                <TableSkeleton columns={6} rows={4} />
              )}
            </SectionCard>
          </div>

          <div className="xl:col-span-2">
            <SectionCard
              title="Conversaciones recientes"
              action={
                <Link
                  href="/conversations"
                  className="flex items-center gap-1 text-xs font-medium text-primary-600 transition hover:text-primary-700"
                >
                  Ver todas <ArrowRight className="h-3 w-3" />
                </Link>
              }
            >
              {data ? (
                <DataTable
                  columns={["Persona", "Estado", "Paso", ""]}
                  rows={(data.latest_conversations || []).map(
                    (conversation) => [
                      conversation.employee?.name || conversation.phone,
                      <Badge key="state">{conversation.state}</Badge>,
                      conversation.current_step || "-",
                      <Link
                        className="text-sm font-medium text-primary-600 transition hover:text-primary-700"
                        href={`/conversations/${encodeURIComponent(conversation.phone)}`}
                        key="detail"
                      >
                        Ver
                      </Link>,
                    ],
                  )}
                />
              ) : (
                <TableSkeleton columns={4} rows={4} />
              )}
            </SectionCard>
          </div>
        </div>

        {data?.alerts && data.alerts.length > 0 && (
          <div className="mt-6 rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <details className="group" open={data.alerts.some((alert) => (alert.severity || "warning") === "error")}>
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-semibold text-gray-900">
                    Alertas operativas
                  </p>
                  <p className="mt-1 text-sm text-gray-500">
                    {data.alerts.length} alertas para revisar en el dashboard.
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600">
                    {data.alerts.length} activas
                  </span>
                  <ChevronDown className="h-4 w-4 text-gray-500 transition group-open:rotate-180" />
                </div>
              </summary>

              <div className="mt-4 space-y-2">
                {data.alerts.map((alert, i) => {
                  const sev = alert.severity || "warning";
                  const linkHref = alert.case_id
                    ? `/cases/${alert.case_id}`
                    : alert.expense_id
                      ? `/expenses/${alert.expense_id}`
                      : "";
                  return (
                    <div
                      key={i}
                      className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm ${severityStyles[sev] || severityStyles.warning}`}
                    >
                      {sev === "error" ? (
                        <XCircle className="h-4 w-4 flex-shrink-0" />
                      ) : (
                        <span
                          className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${severityDot[sev] || severityDot.warning}`}
                        />
                      )}
                      <span className="rounded-full bg-white/70 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide">
                        {severityLabel[sev] || severityLabel.warning}
                      </span>
                      <span className="flex-1">{alert.message}</span>
                      {linkHref && (
                        <Link
                          href={linkHref}
                          className="flex-shrink-0 text-xs font-medium underline"
                        >
                          Ver
                        </Link>
                      )}
                    </div>
                  );
                })}
              </div>
            </details>
          </div>
        )}
      </Shell>
    </ProtectedPage>
  );
}
