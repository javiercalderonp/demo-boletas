"use client";

import { useEffect, useRef } from "react";
import { CheckCircle2, X } from "lucide-react";

type ApproveExpenseDialogProps = {
  merchant: string;
  amount: string;
  loading?: boolean;
  onCancel: () => void;
  onConfirm: () => void | Promise<void>;
};

export function ApproveExpenseDialog({
  merchant,
  amount,
  loading = false,
  onCancel,
  onConfirm,
}: ApproveExpenseDialogProps) {
  const cancelButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelButtonRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !loading) onCancel();
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [loading, onCancel]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/40 px-4"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !loading) onCancel();
      }}
    >
      <div
        aria-describedby="approve-expense-description"
        aria-labelledby="approve-expense-title"
        aria-modal="true"
        className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
        role="dialog"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700">
              <CheckCircle2 className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <h2 id="approve-expense-title" className="text-base font-semibold text-slate-950">
                Aprobar gasto
              </h2>
              <p id="approve-expense-description" className="mt-1 text-sm leading-5 text-slate-600">
                Confirma que revisaste la información antes de aprobar.
              </p>
            </div>
          </div>
          <button
            aria-label="Cerrar"
            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
            disabled={loading}
            onClick={onCancel}
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
          <p className="truncate font-semibold text-slate-900">{merchant}</p>
          <p className="mt-1 text-sm font-bold tabular-nums text-slate-950">{amount}</p>
        </div>

        <div className="mt-5 flex items-center justify-end gap-3">
          <button
            ref={cancelButtonRef}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
            disabled={loading}
            onClick={onCancel}
            type="button"
          >
            Cancelar
          </button>
          <button
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-50"
            disabled={loading}
            onClick={() => void onConfirm()}
            type="button"
          >
            <CheckCircle2 className="h-4 w-4" />
            {loading ? "Aprobando…" : "Aprobar gasto"}
          </button>
        </div>
      </div>
    </div>
  );
}
