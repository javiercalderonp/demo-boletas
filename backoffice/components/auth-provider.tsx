"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { apiRequest, getStoredToken, setStoredLoginEmail, setStoredToken } from "@/lib/api";
import type { BackofficeUser } from "@/lib/types";

type AuthContextValue = {
  token: string | null;
  user: BackofficeUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<BackofficeUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    const savedToken = getStoredToken();
    if (!savedToken) {
      setLoading(false);
      return;
    }
    setToken(savedToken);
    apiRequest<BackofficeUser>("/auth/me", { token: savedToken })
      .then((nextUser) => setUser(nextUser))
      .catch(() => {
        setStoredToken(null);
        setToken(null);
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      user,
      loading,
      async login(email: string, password: string) {
        const data = await apiRequest<{ access_token: string; user: BackofficeUser }>(
          "/auth/login",
          {
            method: "POST",
            body: { email, password },
          },
        );
        setStoredLoginEmail(email);
        setStoredToken(data.access_token);
        setToken(data.access_token);
        setUser(data.user);
        router.push("/");
      },
      logout() {
        setStoredToken(null);
        setToken(null);
        setUser(null);
        router.push("/login");
      },
    }),
    [loading, router, token, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
