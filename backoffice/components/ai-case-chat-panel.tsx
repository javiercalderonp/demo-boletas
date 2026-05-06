"use client";

import { FormEvent, useRef, useState } from "react";
import { Bot, LoaderCircle, Send, Sparkles, User } from "lucide-react";

import { SectionCard } from "@/components/section-card";
import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export function AiCaseChatPanel({ caseId }: { caseId: string }) {
  const { token } = useAuth();
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = input.trim();
    if (!message || !token || loading) return;

    const userMessage: ChatMessage = { role: "user", content: message };
    const nextHistory = [...history, userMessage];
    setHistory(nextHistory);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      const result = await apiRequest<{ answer: string }>(
        `/cases/${caseId}/chat`,
        {
          method: "POST",
          body: { message, history },
          token,
        },
      );
      setHistory([...nextHistory, { role: "assistant", content: result.answer }]);
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo obtener respuesta");
      setHistory(history);
    } finally {
      setLoading(false);
    }
  }

  return (
    <SectionCard
      title={
        <span className="flex items-center gap-1.5">
          <Sparkles className="h-4 w-4 text-violet-500" />
          Asistente IA
        </span>
      }
    >
      <div className="flex flex-col gap-3">
        {history.length === 0 && (
          <p className="rounded-xl border border-dashed border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-600">
            Pregúntame cualquier cosa sobre esta rendición: gastos, saldos, estado, anomalías, etc.
          </p>
        )}

        {history.length > 0 && (
          <div className="max-h-80 space-y-3 overflow-y-auto pr-1">
            {history.map((msg, i) => (
              <div
                key={i}
                className={`flex gap-2 ${msg.role === "user" ? "flex-row-reverse" : "flex-row"}`}
              >
                <div
                  className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full ${
                    msg.role === "user"
                      ? "bg-primary-100 text-primary-700"
                      : "bg-violet-100 text-violet-700"
                  }`}
                >
                  {msg.role === "user" ? (
                    <User className="h-3.5 w-3.5" />
                  ) : (
                    <Bot className="h-3.5 w-3.5" />
                  )}
                </div>
                <div
                  className={`max-w-[88%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed ${
                    msg.role === "user"
                      ? "bg-primary-600 text-white"
                      : "border border-gray-200 bg-white text-gray-800 shadow-sm"
                  }`}
                >
                  {msg.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex gap-2">
                <div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-violet-100 text-violet-700">
                  <Bot className="h-3.5 w-3.5" />
                </div>
                <div className="flex items-center gap-1.5 rounded-xl border border-gray-200 bg-white px-3.5 py-2.5 shadow-sm">
                  <LoaderCircle className="h-3.5 w-3.5 animate-spin text-violet-500" />
                  <span className="text-sm text-gray-400">Analizando...</span>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}

        {error && (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>
        )}

        <form onSubmit={handleSubmit} className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="Pregunta sobre esta rendición..."
            rows={2}
            disabled={loading}
            className="block w-full resize-none rounded-xl border border-gray-300 px-4 py-2.5 text-sm text-gray-900 outline-none transition placeholder:text-gray-400 focus:border-violet-400 focus:ring-2 focus:ring-violet-100 disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-violet-600 text-white shadow-sm transition hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
            title="Enviar pregunta"
          >
            <Send className="h-4 w-4" />
          </button>
        </form>
      </div>
    </SectionCard>
  );
}
