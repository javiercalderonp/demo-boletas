"use client";

import { FormEvent, useState } from "react";
import { X } from "lucide-react";

export const rejectionReasonOptions = [
  "Imagen de mala calidad o ilegible",
  "Documento duplicado",
  "Monto no coincide con lo declarado",
  "Documento no corresponde a un gasto válido",
  "Faltan datos obligatorios",
] as const;

type RejectExpenseDialogProps = {
  title?: string;
  description?: string;
  loading?: boolean;
  onCancel: () => void;
  onConfirm: (reason: string) => void | Promise<void>;
};

export function RejectExpenseDialog({
  title = "Rechazar gasto",
  description = "Selecciona el motivo del rechazo. Este motivo quedará registrado y se incluirá en la notificación al trabajador.",
  loading = false,
  onCancel,
  onConfirm,
}: RejectExpenseDialogProps) {
  const [reason, setReason] = useState<string>(rejectionReasonOptions[0]);
  const [detail, setDetail] = useState("");

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedDetail = detail.trim();
    const fullReason = trimmedDetail ? `${reason}: ${trimmedDetail}` : reason;
    void onConfirm(fullReason);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-base font-semibold text-gray-900">{title}</h3>
            <p className="mt-1 text-sm text-gray-600">{description}</p>
          </div>
          <button
            className="rounded-lg p-1.5 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700"
            onClick={onCancel}
            disabled={loading}
            type="button"
            aria-label="Cerrar"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form className="mt-5 space-y-4" onSubmit={onSubmit}>
          <div>
            <label className="mb-1.5 block text-sm font-medium text-gray-700">
              Motivo
            </label>
            <select
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className="block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-red-500 focus:ring-2 focus:ring-red-100"
              disabled={loading}
            >
              {rejectionReasonOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium text-gray-700">
              Detalle opcional
            </label>
            <textarea
              value={detail}
              onChange={(event) => setDetail(event.target.value)}
              className="block min-h-24 w-full resize-y rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-red-500 focus:ring-2 focus:ring-red-100"
              placeholder="Ej: la boleta está borrosa y no se distingue el monto."
              disabled={loading}
            />
          </div>
          <div className="flex items-center justify-end gap-3">
            <button
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-50"
              onClick={onCancel}
              disabled={loading}
              type="button"
            >
              Cancelar
            </button>
            <button
              className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-red-700 disabled:opacity-50"
              disabled={loading}
              type="submit"
            >
              {loading ? "Rechazando..." : "Confirmar rechazo"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
