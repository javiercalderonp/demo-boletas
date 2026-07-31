"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Download, FileSpreadsheet, LoaderCircle } from "lucide-react";

import { apiRequest, downloadApiFile } from "@/lib/api";
import type { Company, PortaExport, PortaExportPreview } from "@/lib/types";

type Scope = "month" | "range" | "company";

export function PortaAccountingExports({ token, companyId }: { token: string; companyId?: string }) {
  const now = new Date();
  const [scope, setScope] = useState<Scope>("month");
  const [companies, setCompanies] = useState<Company[]>([]);
  const [selectedCompany, setSelectedCompany] = useState(companyId || "");
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [preview, setPreview] = useState<PortaExportPreview | null>(null);
  const [history, setHistory] = useState<PortaExport[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const payload = useMemo(() => ({
    company_id: selectedCompany,
    scope,
    year: scope === "month" ? year : undefined,
    month: scope === "month" ? month : undefined,
    date_from: scope === "range" ? dateFrom : "",
    date_to: scope === "range" ? dateTo : "",
    date_source: "document_date",
  }), [dateFrom, dateTo, month, scope, selectedCompany, year]);

  const loadHistory = useCallback(async () => {
    const response = await apiRequest<{ items: PortaExport[] }>("/porta-exports", { token });
    setHistory(response.items);
  }, [token]);

  useEffect(() => {
    void apiRequest<{ items: Company[] }>("/companies", { token }).then(({ items }) => {
      setCompanies(items);
      if (items.length === 1) setSelectedCompany((current) => current || items[0].company_id);
    });
    void loadHistory();
  }, [loadHistory, token]);

  async function previewExport(event?: FormEvent) {
    event?.preventDefault();
    setLoading(true);
    setError("");
    try {
      setPreview(await apiRequest<PortaExportPreview>("/porta-exports/preview", {
        method: "POST", body: payload, token,
      }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "No se pudo previsualizar.");
    } finally {
      setLoading(false);
    }
  }

  async function generate() {
    setLoading(true);
    setError("");
    try {
      const result = await apiRequest<PortaExport>("/porta-exports", {
        method: "POST", body: payload, token,
      });
      await downloadApiFile(
        `/porta-exports/${result.export_id}/download`,
        token,
        `Rendicion_Porta_${result.export_id}.xlsx`,
      );
      await loadHistory();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "No se pudo generar.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-start gap-3">
          <span className="rounded-xl bg-emerald-50 p-2 text-emerald-700"><FileSpreadsheet className="h-5 w-5" /></span>
          <div><h2 className="font-semibold text-slate-950">Excel Porta</h2><p className="text-sm text-slate-500">La modalidad solo define qué gastos se seleccionan.</p></div>
        </div>
        <form className="mt-5 grid gap-4 md:grid-cols-2 lg:grid-cols-4" onSubmit={previewExport}>
          <label className="text-sm">Empresa
            <select className="mt-1 w-full rounded-lg border p-2" value={selectedCompany} onChange={(event) => setSelectedCompany(event.target.value)} required>
              <option value="">Seleccionar</option>
              {companies.map((company) => <option key={company.company_id} value={company.company_id}>{company.name}</option>)}
            </select>
          </label>
          <label className="text-sm">Modalidad
            <select className="mt-1 w-full rounded-lg border p-2" value={scope} onChange={(event) => { setScope(event.target.value as Scope); setPreview(null); }}>
              <option value="month">Mes</option><option value="range">Rango de fechas</option><option value="company">Empresa completa</option>
            </select>
          </label>
          {scope === "month" && <><label className="text-sm">Año<input className="mt-1 w-full rounded-lg border p-2" type="number" value={year} onChange={(event) => setYear(Number(event.target.value))} /></label><label className="text-sm">Mes<input className="mt-1 w-full rounded-lg border p-2" min="1" max="12" type="number" value={month} onChange={(event) => setMonth(Number(event.target.value))} /></label></>}
          {scope === "range" && <><label className="text-sm">Desde<input className="mt-1 w-full rounded-lg border p-2" type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} required /></label><label className="text-sm">Hasta<input className="mt-1 w-full rounded-lg border p-2" type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} required /></label></>}
          <div className="flex items-end"><button className="w-full rounded-lg border border-emerald-700 px-3 py-2 text-sm font-semibold text-emerald-800 disabled:opacity-50" disabled={loading} type="submit">{loading ? "Consultando…" : "Previsualizar"}</button></div>
        </form>
        <p className="mt-3 text-xs text-slate-500">Regla temporal inicial: fecha del documento. No bloquea períodos ni futuras exportaciones.</p>
        {error && <p className="mt-3 text-sm text-red-700">{error}</p>}
        {preview && <div className="mt-5 rounded-xl bg-slate-50 p-4">
          <div className="grid gap-3 sm:grid-cols-4"><p><span className="block text-xs text-slate-500">Incluidos</span><strong>{preview.included_count}</strong></p><p><span className="block text-xs text-slate-500">Pendientes</span><strong>{preview.excluded_count}</strong></p><p><span className="block text-xs text-slate-500">Casos</span><strong>{preview.case_count}</strong></p><p><span className="block text-xs text-slate-500">Total</span><strong>${preview.total_clp.toLocaleString("es-CL")}</strong></p></div>
          {preview.excluded.length > 0 && <details className="mt-4 text-sm"><summary className="cursor-pointer font-medium text-amber-800">Ver gastos pendientes de corrección</summary><ul className="mt-2 space-y-1 text-xs text-slate-600">{preview.excluded.map((item) => <li key={item.expense_id}>{item.expense_id}: {item.reasons.join(", ")}</li>)}</ul></details>}
          <button className="mt-4 inline-flex items-center gap-2 rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={loading || !preview.included_count} onClick={generate} type="button">{loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}Generar y descargar</button>
        </div>}
      </section>
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="font-semibold text-slate-950">Historial de exportaciones Porta</h2>
        <div className="mt-4 divide-y">{history.length === 0 ? <p className="py-4 text-sm text-slate-500">Sin exportaciones.</p> : history.map((item) => <div className="flex flex-wrap items-center justify-between gap-3 py-3" key={item.export_id}><div><p className="text-sm font-medium">{item.scope} · {item.expense_count} gastos</p><p className="text-xs text-slate-500">{new Date(item.requested_at).toLocaleString("es-CL")} · {item.status}</p></div>{item.status.startsWith("completed") && <button className="text-sm font-semibold text-emerald-700" onClick={() => downloadApiFile(`/porta-exports/${item.export_id}/download`, token, `Rendicion_Porta_${item.export_id}.xlsx`)} type="button">Descargar</button>}</div>)}</div>
      </section>
    </div>
  );
}
