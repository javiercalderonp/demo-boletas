"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Filter, RefreshCw } from "lucide-react";

import { ProtectedPage } from "@/components/protected-page";
import { SectionCard } from "@/components/section-card";
import { Shell } from "@/components/shell";
import { TableSkeleton } from "@/components/table-skeleton";
import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api";
import type { AuditLogItem } from "@/lib/types";

const actionOptions = [
  "",
  "case.create",
  "case.update",
  "case.delete",
  "case.close",
  "expense.approve",
  "expense.reject",
  "expense.observe",
  "conversation.message.send",
  "conversation.template.send",
];

const resourceTypeOptions = ["", "case", "expense", "employee", "conversation", "user"];

function formatDate(value?: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es-CL", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

function formatDetails(details?: Record<string, unknown>): string {
  if (!details || Object.keys(details).length === 0) {
    return "-";
  }
  return Object.entries(details)
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(" · ");
}

function buildQuery(filters: { action: string; resourceType: string; companyId: string; limit: string }) {
  const params = new URLSearchParams();
  if (filters.action) params.set("action", filters.action);
  if (filters.resourceType) params.set("resource_type", filters.resourceType);
  if (filters.companyId.trim()) params.set("company_id", filters.companyId.trim());
  params.set("limit", filters.limit || "200");
  return params.toString();
}

export default function AuditPage() {
  const { token } = useAuth();
  const [items, setItems] = useState<AuditLogItem[] | null>(null);
  const [filters, setFilters] = useState({
    action: "",
    resourceType: "",
    companyId: "",
    limit: "200",
  });
  const [appliedFilters, setAppliedFilters] = useState(filters);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const query = useMemo(() => buildQuery(appliedFilters), [appliedFilters]);

  function load() {
    if (!token) {
      return;
    }
    setLoading(true);
    setError("");
    apiRequest<{ items: AuditLogItem[] }>(`/audit-log?${query}`, { token })
      .then((data) => setItems(data.items))
      .catch((nextError) => setError(nextError.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, [token, query]);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAppliedFilters(filters);
  }

  return (
    <ProtectedPage>
      <Shell
        title="Auditoría"
        description="Historial de acciones realizadas desde el backoffice."
      >
        <div className="space-y-5">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <SectionCard
            title="Filtros"
            action={
              <button
                className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm font-semibold text-gray-700 transition hover:bg-gray-50 disabled:opacity-50"
                disabled={loading}
                onClick={load}
                type="button"
              >
                <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
                Actualizar
              </button>
            }
          >
            <form className="grid gap-4 md:grid-cols-4" onSubmit={onSubmit}>
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">Acción</label>
                <select
                  className="block w-full rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  onChange={(event) => setFilters({ ...filters, action: event.target.value })}
                  value={filters.action}
                >
                  {actionOptions.map((action) => (
                    <option key={action || "all"} value={action}>
                      {action || "Todas"}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">Recurso</label>
                <select
                  className="block w-full rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  onChange={(event) => setFilters({ ...filters, resourceType: event.target.value })}
                  value={filters.resourceType}
                >
                  {resourceTypeOptions.map((resourceType) => (
                    <option key={resourceType || "all"} value={resourceType}>
                      {resourceType || "Todos"}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">Empresa</label>
                <input
                  className="block w-full rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  onChange={(event) => setFilters({ ...filters, companyId: event.target.value })}
                  placeholder="COMP-1"
                  type="text"
                  value={filters.companyId}
                />
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">Límite</label>
                <input
                  className="block w-full rounded-lg border border-gray-300 px-3.5 py-2.5 text-sm outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  max="1000"
                  min="1"
                  onChange={(event) => setFilters({ ...filters, limit: event.target.value })}
                  type="number"
                  value={filters.limit}
                />
              </div>
              <div className="md:col-span-4">
                <button
                  className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700"
                  type="submit"
                >
                  <Filter className="h-4 w-4" />
                  Aplicar filtros
                </button>
              </div>
            </form>
          </SectionCard>

          <SectionCard title={`Eventos${items ? ` (${items.length})` : ""}`}>
            {!items ? (
              <TableSkeleton rows={8} columns={6} />
            ) : items.length === 0 ? (
              <div className="rounded-lg border border-dashed border-gray-200 px-4 py-8 text-center text-sm text-gray-500">
                No hay eventos para los filtros seleccionados.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 text-sm">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600">Fecha</th>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600">Actor</th>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600">Acción</th>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600">Recurso</th>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600">Empresa</th>
                      <th className="px-4 py-3 text-left font-semibold text-gray-600">Detalle</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 bg-white">
                    {items.map((item) => (
                      <tr key={item.audit_id}>
                        <td className="whitespace-nowrap px-4 py-3 text-gray-700">
                          {formatDate(item.timestamp)}
                        </td>
                        <td className="px-4 py-3">
                          <div className="font-medium text-gray-900">{item.user_email || "-"}</div>
                          <div className="text-xs text-gray-500">{item.user_role || "-"}</div>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 font-medium text-gray-900">
                          {item.action || "-"}
                        </td>
                        <td className="px-4 py-3 text-gray-700">
                          <div>{item.resource_type || "-"}</div>
                          <div className="font-mono text-xs text-gray-500">{item.resource_id || "-"}</div>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-gray-700">
                          {item.company_id || "-"}
                        </td>
                        <td className="max-w-md px-4 py-3 text-gray-600">
                          <span className="line-clamp-2" title={formatDetails(item.details)}>
                            {formatDetails(item.details)}
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
