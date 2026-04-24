"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Badge } from "@/components/badge";
import { SectionCard } from "@/components/section-card";
import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api";
import { useAutoRefresh } from "@/lib/use-auto-refresh";
import type { CaseItem, Conversation, ConversationMessage, Employee } from "@/lib/types";

function formatDateTime(value?: string) {
  if (!value) return "Sin fecha";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es-CL", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

export function ChatPanel({
  phone,
  maxHeight = "500px",
}: {
  phone: string;
  maxHeight?: string;
}) {
  const { token } = useAuth();
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [isExpanded, setIsExpanded] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const fetchConversation = useCallback(() => {
    if (!token || !phone) return;
    apiRequest<{ conversation: Conversation; employee: Employee; case: CaseItem }>(
      `/conversations/${encodeURIComponent(phone)}`,
      { token },
    ).then((data) => {
      setConversation(data.conversation);
      setEmployee(data.employee);
    });
  }, [phone, token]);

  useEffect(() => {
    fetchConversation();
  }, [fetchConversation]);

  useAutoRefresh(fetchConversation, {
    enabled: Boolean(token) && Boolean(phone) && !sending,
    intervalMs: 5000,
  });

  const messages = (conversation?.context_json?.message_log || []) as ConversationMessage[];
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  async function handleSendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = chatInput.trim();
    if (!text || !token || !phone) return;

    setSending(true);
    setSendError(null);
    try {
      const result = await apiRequest<{ ok: boolean; conversation: { conversation: Conversation } }>(
        `/conversations/${encodeURIComponent(phone)}/messages`,
        { method: "POST", body: { message: text }, token },
      );
      setChatInput("");
      if (result.conversation) {
        const detail = result.conversation as unknown as {
          conversation: Conversation;
          employee: Employee;
          case: CaseItem;
        };
        if (detail.conversation) {
          setConversation(detail.conversation);
          setEmployee(detail.employee);
        }
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Error al enviar mensaje";
      setSendError(message);
    } finally {
      setSending(false);
    }
  }

  if (!conversation) {
    return (
      <SectionCard
        title="Chat"
        action={
          <button
            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-600 transition hover:bg-gray-50"
            onClick={() => setIsExpanded((current) => !current)}
            type="button"
          >
            {isExpanded ? "Ocultar" : "Ver chat"}
            <ChevronDown className={`h-4 w-4 transition ${isExpanded ? "rotate-180" : ""}`} />
          </button>
        }
      >
        {isExpanded && <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div className={`flex ${i % 2 === 0 ? "justify-start" : "justify-end"}`} key={i}>
              <div className="skeleton h-16 w-full max-w-md rounded-2xl" />
            </div>
          ))}
        </div>}
      </SectionCard>
    );
  }

  return (
    <SectionCard
      title="Chat"
      action={
        <div className="flex items-center gap-2">
          <Badge>{conversation.state}</Badge>
          <button
            aria-expanded={isExpanded}
            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-600 transition hover:bg-gray-50"
            onClick={() => setIsExpanded((current) => !current)}
            type="button"
          >
            {isExpanded ? "Ocultar" : "Ver chat"}
            <ChevronDown className={`h-4 w-4 transition ${isExpanded ? "rotate-180" : ""}`} />
          </button>
        </div>
      }
    >
      {isExpanded && (
        <>
          <div className="overflow-y-auto space-y-4 scroll-smooth" style={{ maxHeight }}>
            {messages.length > 0 ? (
              messages.map((message) => {
                const isPerson = message.speaker === "person";
                const isOperator = message.speaker === "operator";

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
                    <div className={`max-w-[85%] rounded-2xl px-4 py-3 shadow-sm ${bgClasses}`}>
                      <div className="mb-1 flex items-center gap-2 text-xs">
                        <span className={labelColor}>{speakerLabel}</span>
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
                      <p className="whitespace-pre-wrap text-sm leading-6">{message.text}</p>
                      <p className={`mt-2 text-[11px] ${timeColor}`}>
                        {formatDateTime(message.created_at)}
                      </p>
                    </div>
                  </div>
                );
              })
            ) : (
              <p className="text-sm text-gray-500">Sin mensajes.</p>
            )}
            <div ref={messagesEndRef} />
          </div>

          <form onSubmit={handleSendMessage} className="mt-4 flex items-end gap-2 border-t border-gray-200 pt-4">
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
              className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-primary-600 text-white shadow-sm transition hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
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
          {sendError && <p className="mt-2 text-sm text-red-600">{sendError}</p>}
        </>
      )}
    </SectionCard>
  );
}
