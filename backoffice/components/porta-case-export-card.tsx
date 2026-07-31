"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, FileSpreadsheet, LoaderCircle } from "lucide-react";

import { apiRequest, downloadApiFile } from "@/lib/api";
import type { PortaExport, PortaExportPreview } from "@/lib/types";

export function PortaCaseExportCard({ caseId, token }: { caseId: string; token: string }) {
  const [preview, setPreview] = useState<PortaExportPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadPreview = useCallback(async () => {
    try {
      setPreview(await apiRequest<PortaExportPreview>(
        `/cases/${encodeURIComponent(caseId)}/porta-export/preview`,
        { token },
      ));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "No se pudo previsualizar.");
    }
  }, [caseId, token]);

  useEffect(() => { void loadPreview(); }, [loadPreview]);

  async function generate() {
    setLoading(true);
    setError("");
    try {
      const result = await apiRequest<PortaExport>(
        `/cases/${encodeURIComponent(caseId)}/porta-export`,
        { method: "POST", token },
      );
      await downloadApiFile(
        `/porta-exports/${result.export_id}/download`,
        token,
        `Rendicion_Porta_${caseId}.xlsx`,
      );
      await loadPreview();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "No se pudo generar el Excel.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <span className="rounded-xl bg-emerald-50 p-2 text-emerald-700">
          <FileSpreadsheet className="h-5 w-5" />
        </span>
        <div>
          <h2 className="text-sm font-semibold text-slate-950">Exportación contable</h2>
          <p className="mt-1 text-xs text-slate-500">Excel Porta para este caso.</p>
        </div>
      </div>
      {preview && (
        <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-lg bg-slate-50 p-2"><span className="text-slate-500">Incluidos</span><p className="font-semibold">{preview.included_count}</p></div>
          <div className="rounded-lg bg-slate-50 p-2"><span className="text-slate-500">Pendientes</span><p className="font-semibold">{preview.excluded_count}</p></div>
        </div>
      )}
      {error && <p className="mt-3 text-xs text-red-700">{error}</p>}
      <button
        className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-800 disabled:opacity-50"
        disabled={loading || !preview?.included_count}
        onClick={generate}
        type="button"
      >
        {loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
        {loading ? "Generando…" : "Generar Excel Porta"}
      </button>
    </section>
  );
}
