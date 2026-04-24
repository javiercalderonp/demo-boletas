"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/badge";
import { ProtectedPage } from "@/components/protected-page";
import { SectionCard } from "@/components/section-card";
import { Shell } from "@/components/shell";
import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api";
import { useAutoRefresh } from "@/lib/use-auto-refresh";
import type { CaseItem, Conversation, ConversationMessage, Employee } from "@/lib/types";

const fieldLabels: Record<string, string> = {
  case_id: "Case ID",
  state: "Estado",
  current_step: "Paso actual",
};

export default function ConversationDetailPage() {
  const params = useParams<{ phone: string }>();
  const { token } = useAuth();
  const phone = typeof params.phone === "string" ? decodeURIComponent(params.phone) : "";
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [caseItem, setCaseItem] = useState<CaseItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [isTechnicalContextOpen, setIsTechnicalContextOpen] = useState(false);

  // Chat state
  const [chatInput, setChatInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

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
    enabled: Boolean(token) && Boolean(phone) && !saving && !sending,
  });

  // Auto-scroll to bottom when messages change
  const messages = (conversation?.context_json?.message_log || []) as ConversationMessage[];
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !conversation) return;
    setSaving(true);
    try {
      const form = new FormData(event.currentTarget);
      await apiRequest(`/conversations/${encodeURIComponent(phone)}`, {
        method: "PUT",
        body: {
          case_id: form.get("case_id"),
          state: form.get("state"),
          current_step: form.get("current_step"),
          context_json: conversation.context_json,
        },
        token,
      });
      fetchConversation();
    } finally {
      setSaving(false);
    }
  }

  async function handleSendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = chatInput.trim();
    if (!text || !token || !phone) return;

    setSending(true);
    setSendError(null);
    try {
      const result = await apiRequest<{ ok: boolean; conversation: { conversation: Conversation } }>(
        `/conversations/${encodeURIComponent(phone)}/messages`,
        {
          method: "POST",
          body: { message: text },
          token,
        },
      );
      setChatInput("");
      // Update conversation with latest data from response
      if (result.conversation) {
        const detail = result.conversation as unknown as {
          conversation: Conversation;
          employee: Employee;
          case: CaseItem;
        };
        if (detail.conversation) {
          setConversation(detail.conversation);
          setEmployee(detail.employee);
          setCaseItem(detail.case);
        }
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Error al enviar mensaje";
      setSendError(message);
    } finally {
      setSending(false);
    }
  }

  return (
    <ProtectedPage>
      <Shell title="Detalle de conversación" description={phone}>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <SectionCard
              title="Conversación"
              action={
                conversation ? (
                  <div className="flex items-center gap-2">
                    <Badge>{conversation.state}</Badge>
                  </div>
                ) : null
              }
            >
              {conversation ? (
                <>
                  {/* Message history */}
                  <div
                    ref={chatContainerRef}
                    className="max-h-[500px] overflow-y-auto space-y-4 scroll-smooth"
                  >
                    {messages.length > 0 ? (
                      messages.map((message) => {
                        const isPerson = message.speaker === "person";
                        const isOperator = message.speaker === "operator";
                        const isBot = !isPerson && !isOperator;

                        let alignment = "justify-start";
                        let bgClasses = "border border-gray-200 bg-white text-gray-900";
                        let labelColor = "text-gray-500";
                        let timeColor = "text-gray-400";
                        let speakerLabel = "Bot";

                        if (isPerson) {
                          alignment = "justify-end";
                          bgClasses = "bg-primary-600 text-white";
                          labelColor = "text-primary-50/90";
                          timeColor = "text-primary-100/90";
                          speakerLabel = employee?.name || "Persona";
                        } else if (isOperator) {
                          alignment = "justify-end";
                          bgClasses = "bg-amber-600 text-white";
                          labelColor = "text-amber-50/90";
                          timeColor = "text-amber-100/90";
                          speakerLabel = message.operator_name || "Operador";
                        }

                        return (
                          <div className={`flex ${alignment}`} key={message.id}>
                            <div
                              className={`max-w-[85%] rounded-2xl px-4 py-3 shadow-sm ${bgClasses}`}
                            >
                              <div className="mb-1 flex items-center gap-2 text-xs">
                                <span className={labelColor}>
                                  {speakerLabel}
                                </span>
                                {isOperator && (
                                  <span className="rounded-full bg-amber-500/30 px-1.5 py-0.5 text-[10px] font-medium text-amber-50">
                                    Operador
                                  </span>
                                )}
                                {message.type === "media" && (
                                  <span className={isPerson ? "text-primary-100/90" : "text-gray-400"}>
                                    Adjunto
                                  </span>
                                )}
                              </div>
                              <p className="whitespace-pre-wrap text-sm leading-6">
                                {message.text}
                              </p>
                              <p className={`mt-2 text-[11px] ${timeColor}`}>
                                {formatDateTime(message.created_at)}
                              </p>
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <p className="text-sm text-gray-500">
                        Aun no hay mensajes guardados para esta conversación.
                      </p>
                    )}
                    <div ref={messagesEndRef} />
                  </div>

                  {/* Chat input */}
                  <form
                    onSubmit={handleSendMessage}
                    className="mt-4 flex items-end gap-2 border-t border-gray-200 pt-4"
                  >
                    <div className="flex-1">
                      <textarea
                        value={chatInput}
                        onChange={(e) => setChatInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.shiftKey) {
                            e.preventDefault();
                            e.currentTarget.form?.requestSubmit();
                          }
                        }}
                        placeholder="Escribe un mensaje para enviar por WhatsApp..."
                        rows={2}
                        className="block w-full resize-none rounded-xl border border-gray-300 px-4 py-2.5 text-sm text-gray-900 outline-none transition placeholder:text-gray-400 focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                        disabled={sending}
                      />
                    </div>
                    <button
                      type="submit"
                      disabled={sending || !chatInput.trim()}
                      className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-primary-600 text-white shadow-sm transition hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed"
                      title="Enviar mensaje"
                    >
                      {sending ? (
                        <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                      ) : (
                        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <line x1="22" y1="2" x2="11" y2="13" />
                          <polygon points="22 2 15 22 11 13 2 9 22 2" />
                        </svg>
                      )}
                    </button>
                  </form>
                  {sendError && (
                    <p className="mt-2 text-sm text-red-600">{sendError}</p>
                  )}
                </>
              ) : (
                <div className="space-y-4">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <div
                      className={`flex ${i % 2 === 0 ? "justify-start" : "justify-end"}`}
                      key={i}
                    >
                      <div className="skeleton h-20 w-full max-w-md rounded-2xl" />
                    </div>
                  ))}
                </div>
              )}
            </SectionCard>

            <div className="mt-6">
              <SectionCard title="Estado actual">
                {conversation ? (
                  <form
                    key={JSON.stringify([
                      conversation.case_id || "",
                      conversation.state || "",
                      conversation.current_step || "",
                    ])}
                    className="space-y-4"
                    onSubmit={onSubmit}
                  >
                    {(["case_id", "state", "current_step"] as const).map((field) => (
                      <div key={field}>
                        <label className="mb-1.5 block text-sm font-medium text-gray-700">
                          {fieldLabels[field]}
                        </label>
                        <input
                          defaultValue={String(conversation[field as keyof Conversation] || "")}
                          name={field}
                          className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                        />
                      </div>
                    ))}
                    <button
                      className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700 disabled:opacity-50"
                      type="submit"
                      disabled={saving}
                    >
                      {saving ? "Guardando..." : "Actualizar"}
                    </button>
                  </form>
                ) : (
                  <div className="space-y-4">
                    {Array.from({ length: 3 }).map((_, i) => (
                      <div key={i}>
                        <div className="skeleton mb-1.5 h-4 w-20" />
                        <div className="skeleton h-9 w-full rounded-lg" />
                      </div>
                    ))}
                  </div>
                )}
              </SectionCard>
            </div>
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

function formatDateTime(value?: string) {
  if (!value) {
    return "Sin fecha";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("es-CL", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}
