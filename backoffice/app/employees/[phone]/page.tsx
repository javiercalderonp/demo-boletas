"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { DataTable } from "@/components/data-table";
import { Badge } from "@/components/badge";
import { ProtectedPage } from "@/components/protected-page";
import { SectionCard } from "@/components/section-card";
import { Shell } from "@/components/shell";
import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api";
import { useAutoRefresh } from "@/lib/use-auto-refresh";
import type { CaseItem, Company, Conversation, Employee, Expense } from "@/lib/types";

const fieldLabels: Record<string, string> = {
  first_name: "Nombre",
  last_name: "Apellido",
  rut: "RUT",
  email: "Email",
  bank_name: "Banco",
  account_type: "Tipo de cuenta",
  account_number: "Número de cuenta",
  account_holder: "Titular",
  account_holder_rut: "RUT titular",
};

export default function EmployeeDetailPage() {
  const params = useParams<{ phone: string }>();
  const { token } = useAuth();
  const phone = typeof params.phone === "string" ? decodeURIComponent(params.phone) : "";
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [saving, setSaving] = useState(false);

  function fetchEmployeeDetail() {
    if (!token || !phone) {
      return;
    }
    return Promise.all([
      apiRequest<{
        employee: Employee;
        cases: CaseItem[];
        expenses: Expense[];
        conversations: Conversation[];
      }>(`/employees/${encodeURIComponent(phone)}`, { token }),
      apiRequest<{ items: Company[] }>("/companies", { token }),
    ]).then(([data, companiesData]) => {
      setEmployee(data.employee);
      setCases(data.cases);
      setExpenses(data.expenses);
      setConversations(data.conversations);
      setCompanies(companiesData.items.filter((company) => company.active));
    });
  }

  useEffect(() => {
    void fetchEmployeeDetail();
  }, [phone, token]);

  useAutoRefresh(() => fetchEmployeeDetail(), {
    enabled: Boolean(token) && Boolean(phone) && !saving,
  });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !employee) {
      return;
    }
    setSaving(true);
    try {
      const form = new FormData(event.currentTarget);
      const payload = Object.fromEntries(form.entries());
      await apiRequest(`/employees/${encodeURIComponent(phone)}`, {
        method: "PUT",
        body: { ...employee, ...payload, active: employee.active },
        token,
      });
      await fetchEmployeeDetail();
    } finally {
      setSaving(false);
    }
  }

  return (
    <ProtectedPage>
      <Shell title="Detalle de persona" description={phone}>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <SectionCard title="Datos básicos">
            {employee ? (
              <form
                key={JSON.stringify([
                  employee.company_id || "",
                  employee.rut || "",
                  employee.first_name || "",
                  employee.last_name || "",
                  employee.email || "",
                  employee.bank_name || "",
                  employee.account_type || "",
                  employee.account_number || "",
                  employee.account_holder || "",
                  employee.account_holder_rut || "",
                ])}
                className="space-y-4"
                onSubmit={onSubmit}
              >
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">
                    Empresa
                  </label>
                  <select
                    name="company_id"
                    defaultValue={employee.company_id || ""}
                    className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  >
                    <option value="">Selecciona una empresa</option>
                    {companies.map((company) => (
                      <option key={company.company_id} value={company.company_id}>
                        {company.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">
                    {fieldLabels.rut}
                  </label>
                  <input
                    defaultValue={employee.rut || ""}
                    name="rut"
                    className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">
                    {fieldLabels.first_name}
                  </label>
                  <input
                    defaultValue={employee.first_name || ""}
                    name="first_name"
                    className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">
                    {fieldLabels.last_name}
                  </label>
                  <input
                    defaultValue={employee.last_name || ""}
                    name="last_name"
                    className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">
                    {fieldLabels.email}
                  </label>
                  <input
                    defaultValue={employee.email || ""}
                    name="email"
                    className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                  />
                </div>
                <details className="rounded-xl border border-gray-200 bg-gray-50">
                  <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-gray-900">
                    Datos bancarios opcionales
                  </summary>
                  <div className="grid gap-4 border-t border-gray-200 bg-white p-4">
                    <div>
                      <label className="mb-1.5 block text-sm font-medium text-gray-700">
                        {fieldLabels.bank_name}
                      </label>
                      <input
                        defaultValue={employee.bank_name || ""}
                        name="bank_name"
                        className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-sm font-medium text-gray-700">
                        {fieldLabels.account_type}
                      </label>
                      <input
                        defaultValue={employee.account_type || ""}
                        name="account_type"
                        className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                      />
                    </div>
                    {(["account_number", "account_holder", "account_holder_rut"] as const).map((field) => (
                      <div key={field}>
                        <label className="mb-1.5 block text-sm font-medium text-gray-700">
                          {fieldLabels[field]}
                        </label>
                        <input
                          defaultValue={employee[field] || ""}
                          name={field}
                          className="block w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm text-gray-900 outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                        />
                      </div>
                    ))}
                  </div>
                </details>
                <button
                  className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-primary-700 disabled:opacity-50"
                  type="submit"
                  disabled={saving}
                >
                  {saving ? "Guardando..." : "Guardar cambios"}
                </button>
              </form>
            ) : (
              <div className="space-y-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i}>
                    <div className="skeleton mb-1.5 h-4 w-16" />
                    <div className="skeleton h-9 w-full rounded-lg" />
                  </div>
                ))}
              </div>
            )}
          </SectionCard>

          <SectionCard title="Casos asociados">
            <DataTable
              columns={["Case", "Estado", "Empresa", ""]}
              rows={cases.map((item) => [
                <span key="id" className="font-mono text-xs">{item.case_id}</span>,
                <Badge key="status">{item.status}</Badge>,
                item.company_id || "-",
                <Link
                  className="text-sm font-medium text-primary-600 hover:text-primary-700 transition"
                  href={`/cases/${item.case_id}`}
                  key={item.case_id}
                >
                  Ver caso
                </Link>,
              ])}
            />
          </SectionCard>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-5">
          <div className="xl:col-span-3">
            <SectionCard title="Gastos asociados">
              <DataTable
                columns={["Expense", "Merchant", "Monto", "Estado", ""]}
                rows={expenses.map((item) => [
                  <span key="id" className="font-mono text-xs">{item.expense_id}</span>,
                  item.merchant || "-",
                  `${item.currency || ""} ${item.total || "-"}`,
                  <Badge key="status">{item.status || "-"}</Badge>,
                  <Link
                    className="text-sm font-medium text-primary-600 hover:text-primary-700 transition"
                    href={`/expenses/${item.expense_id}`}
                    key={`expense-${item.expense_id}`}
                  >
                    Ver gasto
                  </Link>,
                ])}
              />
            </SectionCard>
          </div>
          <div className="xl:col-span-2">
            <SectionCard title="Conversaciones">
              <DataTable
                columns={["Estado", "Paso", "Actualizado"]}
                rows={conversations.map((item) => [
                  <Badge key="state">{item.state}</Badge>,
                  item.current_step || "-",
                  <span key="date" className="text-xs text-gray-500">{item.updated_at || "-"}</span>,
                ])}
              />
            </SectionCard>
          </div>
        </div>
      </Shell>
    </ProtectedPage>
  );
}
