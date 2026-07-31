"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";

export function ProtectedPage({
  children,
  requireGlobalAdmin = false,
}: {
  children: React.ReactNode;
  requireGlobalAdmin?: boolean;
}) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.push("/login");
    } else if (
      !loading &&
      requireGlobalAdmin &&
      user &&
      !(user.scope_type === "global" && (user.role === "super_admin" || user.role === "admin"))
    ) {
      router.replace("/");
    }
  }, [loading, requireGlobalAdmin, router, user]);

  const unauthorized =
    requireGlobalAdmin &&
    user &&
    !(user.scope_type === "global" && (user.role === "super_admin" || user.role === "admin"));

  if (loading || !user || unauthorized) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary-600 border-t-transparent" />
          <p className="text-sm text-gray-500">Cargando sesión...</p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
