"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ChatPanel } from "@/components/chat-panel";
import { ProtectedPage } from "@/components/protected-page";
import { SectionCard } from "@/components/section-card";
import { Shell } from "@/components/shell";
import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api";
import { useAutoRefresh } from "@/lib/use-auto-refresh";
import type { CaseItem, Conversation, Employee } from "@/lib/types";

export default function ConversationDetailPage() {
  const params = useParams<{ phone: string }>();
  const { token } = useAuth();
  const phone = typeof params.phone === "string" ? decodeURIComponent(params.phone) : "";
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [caseItem, setCaseItem] = useState<CaseItem | null>(null);
  const [isTechnicalContextOpen, setIsTechnicalContextOpen] = useState(false);

  const fetchConversation = useCallback(() => {
    if (!token || !phone) return;
    apiRequest<{ conversation: Conversation; employee: Employee; case: CaseItem }>(
      `/conversations/${encodeURIComponent(phone)}`,
      { token },
    ).then((data) => {
      setConversation(data.conversation);
      setEmployee(data.employee);
      setCaseItem(data.case);
    });
  }, [phone, token]);

  // Initial fetch
  useEffect(() => {
    fetchConversation();
  }, [fetchConversation]);

  useAutoRefresh(fetchConversation, {
    enabled: Boolean(token) && Boolean(phone),
  });

  return (
    <ProtectedPage>
      <Shell title="Detalle de conversación" description={phone}>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <ChatPanel phone={phone} maxHeight="min(70vh, 760px)" />
          </div>

          <div>
            <SectionCard title="Vínculos">
              <div className="space-y-3">
                {employee && (
                  <Link
                    className="flex items-center gap-3 rounded-lg border border-gray-200 p-3 transition hover:bg-gray-50"
                    href={`/employees/${encodeURIComponent(employee.phone)}`}
                  >
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary-100 text-primary-700 text-sm font-semibold">
                      {employee.name?.charAt(0)?.toUpperCase() || "?"}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-gray-900">{employee.name}</p>
                      <p className="text-xs text-gray-500">Persona</p>
                    </div>
                  </Link>
                )}
                {caseItem && (
                  <Link
                    className="flex items-center gap-3 rounded-lg border border-gray-200 p-3 transition hover:bg-gray-50"
                    href={`/cases/${caseItem.case_id}`}
                  >
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-100 text-blue-700 text-sm font-semibold">
                      C
                    </div>
                    <div>
                      <p className="text-sm font-medium text-gray-900 font-mono">{caseItem.case_id}</p>
                      <p className="text-xs text-gray-500">Caso</p>
                    </div>
                  </Link>
                )}
                {!employee && !caseItem && (
                  <p className="text-sm text-gray-500">Sin vínculos disponibles.</p>
                )}
              </div>
            </SectionCard>
          </div>
        </div>

        <div className="mt-6">
          <SectionCard
            title="Contexto técnico"
            action={
              <button
                type="button"
                onClick={() => setIsTechnicalContextOpen((current) => !current)}
                className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-1.5 text-sm font-medium text-gray-600 transition hover:bg-gray-50"
                aria-expanded={isTechnicalContextOpen}
              >
                <span>{isTechnicalContextOpen ? "Ocultar" : "Ver"}</span>
                <span className="font-mono text-xs">{isTechnicalContextOpen ? "˄" : "˅"}</span>
              </button>
            }
          >
            {isTechnicalContextOpen ? (
              <pre className="overflow-x-auto rounded-lg bg-gray-900 p-4 font-mono text-sm leading-relaxed text-gray-100">
                {JSON.stringify(conversation?.context_json || {}, null, 2)}
              </pre>
            ) : (
              <p className="text-sm text-gray-500">
                El contexto técnico está colapsado para facilitar la lectura.
              </p>
            )}
          </SectionCard>
        </div>
      </Shell>
    </ProtectedPage>
  );
}
