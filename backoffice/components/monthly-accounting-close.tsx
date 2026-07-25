"use client";

import { AlertTriangle, Download, FileArchive, FileSpreadsheet, FileText, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/badge";
import { SectionCard } from "@/components/section-card";
import { apiRequest, downloadApiFile } from "@/lib/api";
import type {
  AccountingExport,
  AccountingExportPreview,
  Company,
} from "@/lib/types";

type CompaniesResponse = { items: Company[] };
type ExportsResponse = { items: AccountingExport[] };

const statusLabels: Record<string, string> = {
  queued: "En cola",
  processing: "Generando",
  completed: "Listo",
  completed_with_warnings: "Listo con advertencias",
  failed: "Error",
  expired: "Expirado",
};

function previousMonth(): { year: number; month: number } {
  const date = new Date();
  date.setDate(1);
  date.setMonth(date.getMonth() - 1);
  return { year: date.getFullYear(), month: date.getMonth() + 1 };
}

function formatCLP(value: number): string {
  return `$${value.toLocaleString("es-CL", { maximumFractionDigits: 0 })}`;
}

export function MonthlyAccountingClose({ token }: { token: string }) {
  const defaultPeriod = previousMonth();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [history, setHistory] = useState<AccountingExport[]>([]);
  const [companyId, setCompanyId] = useState("");
  const [year, setYear] = useState(defaultPeriod.year);
  const [month, setMonth] = useState(defaultPeriod.month);
  const [preview, setPreview] = useState<AccountingExportPreview | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");

  const loadHistory = useCallback(async () => {
    const result = await apiRequest<ExportsResponse>("/accounting-exports", { token });
    setHistory(result.items);
  }, [token]);

  useEffect(() => {
    Promise.all([
      apiRequest<CompaniesResponse>("/companies", { token }),
      apiRequest<ExportsResponse>("/accounting-exports", { token }),
    ])
      .then(([companyResult, exportResult]) => {
        const activeCompanies = companyResult.items.filter((company) => company.active);
        setCompanies(activeCompanies);
        setCompanyId((current) => current || activeCompanies[0]?.company_id || "");
        setHistory(exportResult.items);
      })
      .catch((nextError: Error) => setError(nextError.message));
  }, [token]);

  const loadPreview = useCallback(async () => {
    if (!companyId) return;
    setError("");
    const query = new URLSearchParams({
      company_id: companyId,
      year: String(year),
      month: String(month),
    });
    try {
      const result = await apiRequest<AccountingExportPreview>(
        `/accounting-exports/preview?${query.toString()}`,
        { token },
      );
      setPreview(result);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "No se pudo cargar la vista previa.");
    }
  }, [companyId, month, token, year]);

  useEffect(() => {
    void loadPreview();
  }, [loadPreview]);

  async function generate(): Promise<void> {
    setGenerating(true);
    setError("");
    try {
      await apiRequest<AccountingExport>("/accounting-exports", {
        method: "POST",
        token,
        body: { company_id: companyId, year, month, include_csv: true },
      });
      await loadHistory();
      setModalOpen(false);
      await loadPreview();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "No se pudo generar el paquete.");
    } finally {
      setGenerating(false);
    }
  }

  async function download(item: AccountingExport, format: "pdf" | "xlsx" | "zip"): Promise<void> {
    setError("");
    try {
      await downloadApiFile(
        `/accounting-exports/${item.export_id}/download?format=${format}`,
        token,
        `Cierre_${item.period_year}-${String(item.period_month).padStart(2, "0")}.${format}`,
      );
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "No se pudo descargar.");
    }
  }

  return (
    <>
      <SectionCard
        title="Cierre contable mensual"
        action={
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            disabled={!companyId}
            className="rounded-lg bg-primary-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-primary-700 disabled:opacity-50"
          >
            Generar paquete contable
          </button>
        }
      >
        {error && <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs font-medium text-gray-600">
            Empresa
            <select
              value={companyId}
              onChange={(event) => setCompanyId(event.target.value)}
              className="mt-1 block rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900"
            >
              {companies.map((company) => (
                <option key={company.company_id} value={company.company_id}>{company.name}</option>
              ))}
            </select>
          </label>
          <label className="text-xs font-medium text-gray-600">
            Mes
            <select value={month} onChange={(event) => setMonth(Number(event.target.value))} className="mt-1 block rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm">
              {Array.from({ length: 12 }, (_, index) => index + 1).map((value) => <option key={value} value={value}>{String(value).padStart(2, "0")}</option>)}
            </select>
          </label>
          <label className="text-xs font-medium text-gray-600">
            Año
            <input type="number" min={2000} max={2100} value={year} onChange={(event) => setYear(Number(event.target.value))} className="mt-1 block w-24 rounded-lg border border-gray-300 px-3 py-2 text-sm" />
          </label>
          <button type="button" onClick={() => void loadPreview()} className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">Vista previa</button>
        </div>

        {preview && (
          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
            {[
              ["Rendiciones", preview.case_count],
              ["Gastos", preview.expense_count],
              ["Total rendido", formatCLP(preview.total_clp)],
              ["Aprobados", preview.approved_count],
              ["Pendientes", preview.pending_count],
              ["Rechazados", preview.rejected_count],
              ["Observados", preview.observed_count],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg bg-gray-50 p-3">
                <p className="text-[11px] text-gray-500">{label}</p>
                <p className="mt-1 text-sm font-semibold text-gray-900">{value}</p>
              </div>
            ))}
          </div>
        )}

        {history.length > 0 && (
          <div className="mt-5 overflow-x-auto border-t border-gray-100 pt-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">Últimas exportaciones</p>
            <table className="w-full text-left text-xs">
              <thead><tr className="text-gray-500"><th className="pb-2">Periodo</th><th className="pb-2">Generado por</th><th className="pb-2">Estado</th><th className="pb-2">Gastos</th><th className="pb-2">Total</th><th className="pb-2">Acciones</th></tr></thead>
              <tbody>
                {history.slice(0, 5).map((item) => (
                  <tr key={item.export_id} className="border-t border-gray-100">
                    <td className="py-2">{item.period_year}-{String(item.period_month).padStart(2, "0")}</td>
                    <td className="py-2">{item.requested_by}</td>
                    <td className="py-2"><Badge>{statusLabels[item.status] || item.status}</Badge></td>
                    <td className="py-2">{item.expense_count}</td>
                    <td className="py-2">{formatCLP(Number(item.total_clp))}</td>
                    <td className="py-2">
                      <div className="flex gap-1">
                        {(["pdf", "xlsx", "zip"] as const).map((format) => item.downloads[format] && (
                          <button key={format} type="button" onClick={() => void download(item, format)} className="rounded p-1 text-primary-600 hover:bg-primary-50" aria-label={`Descargar ${format.toUpperCase()}`}>
                            <Download className="h-4 w-4" />
                          </button>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {modalOpen && preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-labelledby="accounting-close-title">
          <div className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-xl bg-white p-6 shadow-xl">
            <div className="flex items-start justify-between">
              <div>
                <h2 id="accounting-close-title" className="text-lg font-semibold text-gray-900">Confirmar cierre contable</h2>
                <p className="mt-1 text-sm text-gray-500">{preview.company_name} · {preview.period}</p>
              </div>
              <button type="button" onClick={() => setModalOpen(false)} aria-label="Cerrar"><X className="h-5 w-5" /></button>
            </div>
            <div className="mt-5 grid grid-cols-3 gap-3">
              <div className="rounded-lg bg-gray-50 p-3"><FileText className="h-4 w-4 text-primary-600" /><p className="mt-2 text-xs">Informe PDF</p></div>
              <div className="rounded-lg bg-gray-50 p-3"><FileSpreadsheet className="h-4 w-4 text-emerald-600" /><p className="mt-2 text-xs">Detalle Excel</p></div>
              <div className="rounded-lg bg-gray-50 p-3"><FileArchive className="h-4 w-4 text-amber-600" /><p className="mt-2 text-xs">ZIP + respaldos</p></div>
            </div>
            {preview.warnings.length > 0 && (
              <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-4">
                <p className="flex items-center gap-2 text-sm font-semibold text-amber-900"><AlertTriangle className="h-4 w-4" /> Advertencias</p>
                <ul className="mt-2 space-y-1 text-sm text-amber-800">{preview.warnings.map((warning) => <li key={warning.type}>• {warning.description}</li>)}</ul>
              </div>
            )}
            <p className="mt-5 text-xs text-gray-500">El paquete es un respaldo administrativo y no reemplaza documentos tributarios ni libros contables.</p>
            <div className="mt-6 flex justify-end gap-2">
              <button type="button" onClick={() => setModalOpen(false)} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium">Cancelar</button>
              <button type="button" onClick={() => void generate()} disabled={generating} className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{generating ? "Generando…" : "Confirmar y generar"}</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
