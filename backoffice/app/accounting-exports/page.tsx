"use client";

import { ProtectedPage } from "@/components/protected-page";
import { PortaAccountingExports } from "@/components/porta-accounting-exports";
import { Shell } from "@/components/shell";
import { useAuth } from "@/components/auth-provider";

export default function AccountingExportsPage() {
  const { token, user } = useAuth();
  return (
    <ProtectedPage>
      <Shell title="Exportación contable" description="Exportaciones Porta por mes, rango o empresa completa.">
        {token && <PortaAccountingExports token={token} companyId={user?.company_id} />}
      </Shell>
    </ProtectedPage>
  );
}
