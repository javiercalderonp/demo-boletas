"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";

import { DataTable } from "@/components/data-table";
import { Badge } from "@/components/badge";
import { ProtectedPage } from "@/components/protected-page";
import { SectionCard } from "@/components/section-card";
import { Shell } from "@/components/shell";
import { TableSkeleton } from "@/components/table-skeleton";
import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api";
import { useAutoRefresh } from "@/lib/use-auto-refresh";
import type { Conversation } from "@/lib/types";

export default function ConversationsPage() {
  const { token } = useAuth();
  const [items, setItems] = useState<Conversation[] | null>(null);
  const [stateFilter, setStateFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  function load() {
    if (!token) {
      return;
    }
    apiRequest<{ items: Conversation[] }>("/conversations", { token }).then((data) =>
      setItems(data.items),
    );
  }

  useEffect(() => {
    load();
  }, [token]);

  useAutoRefresh(
    () => load(),
    { enabled: Boolean(token) },
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const nextState = params.get("state") || "";
    setStateFilter(nextState);
    setSearchQuery(params.get("q") || "");
  }, []);

  const filteredItems = useMemo(() => {
    if (!items) return null;

    return items.filter((conversation) => {
      const normalizedState = String(conversation.state || "").trim().toUpperCase();
      const matchesState =
        !stateFilter ||
        (stateFilter === "active"
          ? normalizedState !== "DONE" && normalizedState !== ""
          : normalizedState === stateFilter.trim().toUpperCase());

      if (!matchesState) {
        return false;
      }

      if (!searchQuery.trim()) {
        return true;
      }

      const q = searchQuery.trim().toLowerCase();
      return [
        conversation.phone,
        conversation.employee?.name,
        conversation.case_id,
        conversation.state,
        conversation.current_step,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(q));
    });
  }, [items, searchQuery, stateFilter]);

  async function resolve(phone: string) {
    if (!token) {
      return;
    }
    await apiRequest(`/conversations/${encodeURIComponent(phone)}/actions`, {
      method: "POST",
      body: { action: "resolve" },
      token,
    });
    load();
  }

  return (
    <ProtectedPage>
      <Shell title="Conversaciones" description="Monitoreo del estado conversacional del bot.">
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[220px] max-w-md">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="Buscar por persona, teléfono o case..."
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              className="block w-full rounded-lg border border-gray-300 py-2 pl-9 pr-3 text-sm text-gray-900 outline-none transition placeholder:text-gray-400 focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
            />
          </div>
          <select
            value={stateFilter}
            onChange={(event) => setStateFilter(event.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
          >
            <option value="">Todos los estados</option>
            <option value="active">Activas</option>
            <option value="WAIT_RECEIPT">WAIT_RECEIPT</option>
            <option value="PROCESSING">PROCESSING</option>
            <option value="NEEDS_INFO">NEEDS_INFO</option>
            <option value="CONFIRM_SUMMARY">CONFIRM_SUMMARY</option>
            <option value="WAIT_SUBMISSION_CLOSURE_CONFIRMATION">WAIT_SUBMISSION_CLOSURE_CONFIRMATION</option>
            <option value="DONE">DONE</option>
          </select>
          {(searchQuery || stateFilter) && (
            <button
              type="button"
              onClick={() => {
                setSearchQuery("");
                setStateFilter("");
              }}
              className="text-xs text-gray-500 underline hover:text-gray-700"
            >
              Limpiar filtros
            </button>
          )}
        </div>
        <SectionCard title="Listado de conversaciones">
          {filteredItems === null ? (
            <TableSkeleton columns={7} rows={6} />
          ) : (
            <DataTable
              columns={["Teléfono", "Persona", "Case", "Estado", "Paso actual", "Actualizado", ""]}
              rows={filteredItems.map((conversation) => [
                <span key="phone" className="font-mono text-xs">{conversation.phone}</span>,
                conversation.employee?.name || "-",
                conversation.case_id ? (
                  <span key="case" className="font-mono text-xs">{conversation.case_id}</span>
                ) : (
                  "-"
                ),
                <Badge key="state">{conversation.state}</Badge>,
                conversation.current_step || "-",
                <span key="date" className="text-xs text-gray-500">{conversation.updated_at || "-"}</span>,
                <div className="flex items-center gap-2" key={conversation.phone}>
                  <Link
                    className="text-sm font-medium text-primary-600 hover:text-primary-700 transition"
                    href={`/conversations/${encodeURIComponent(conversation.phone)}`}
                  >
                    Ver
                  </Link>
                  <button
                    className="text-sm font-medium text-gray-500 hover:text-gray-700 transition"
                    onClick={() => resolve(conversation.phone)}
                    type="button"
                  >
                    Resolver
                  </button>
                </div>,
              ])}
              rowHrefs={filteredItems.map((conversation) => `/conversations/${encodeURIComponent(conversation.phone)}`)}
            />
          )}
        </SectionCard>
      </Shell>
    </ProtectedPage>
  );
}
