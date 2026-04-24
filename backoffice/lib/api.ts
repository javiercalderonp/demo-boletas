import { emitApiMutation } from "@/lib/api-events";

const DEFAULT_LOCAL_API_BASE_URL = "http://localhost:8000/api";
const DEFAULT_PRODUCTION_API_BASE_URL =
  "https://viaticos-backend-337678027134.us-central1.run.app/api";
const BACKOFFICE_TOKEN_STORAGE_KEY = "backoffice_token";
const BACKOFFICE_LOGIN_EMAIL_STORAGE_KEY = "backoffice_login_email";

function normalizeApiBaseUrl(value: string): string {
  return value.replace(/\/+$/, "");
}

function shouldAvoidLocalhostApi(url: URL): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  const currentHost = window.location.hostname;
  const isCurrentHostLocal =
    currentHost === "localhost" ||
    currentHost === "127.0.0.1" ||
    currentHost === "::1";
  const isApiHostLocal =
    url.hostname === "localhost" ||
    url.hostname === "127.0.0.1" ||
    url.hostname === "::1";
  return !isCurrentHostLocal && isApiHostLocal;
}

function resolveApiBaseUrl(): string {
  const configuredBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (configuredBaseUrl) {
    try {
      const parsed = new URL(configuredBaseUrl);
      if (!shouldAvoidLocalhostApi(parsed)) {
        return normalizeApiBaseUrl(configuredBaseUrl);
      }
    } catch {
      return normalizeApiBaseUrl(configuredBaseUrl);
    }
  }

  if (typeof window !== "undefined") {
    const currentHost = window.location.hostname;
    const isCurrentHostLocal =
      currentHost === "localhost" ||
      currentHost === "127.0.0.1" ||
      currentHost === "::1";

    if (isCurrentHostLocal) {
      return DEFAULT_LOCAL_API_BASE_URL;
    }

    return DEFAULT_PRODUCTION_API_BASE_URL;
  }

  return DEFAULT_LOCAL_API_BASE_URL;
}

export function getApiBaseUrl(): string {
  return resolveApiBaseUrl();
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  token?: string | null;
};

export async function apiRequest<T>(
  path: string,
  { method = "GET", body, token }: RequestOptions = {},
): Promise<T> {
  const apiBaseUrl = getApiBaseUrl();
  const normalizedMethod = method.toUpperCase();
  let response: Response;

  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      method: normalizedMethod,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new Error("No se pudo conectar con la API.");
  }

  if (!response.ok) {
    let detail = "No se pudo completar la solicitud.";
    try {
      const data = await response.json();
      detail = data.detail || detail;
    } catch {}
    throw new Error(detail);
  }

  if (normalizedMethod !== "GET" && normalizedMethod !== "HEAD") {
    emitApiMutation({ method: normalizedMethod, path });
  }

  return response.json() as Promise<T>;
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(BACKOFFICE_TOKEN_STORAGE_KEY);
}

export function setStoredToken(token: string | null): void {
  if (typeof window === "undefined") {
    return;
  }
  if (!token) {
    window.localStorage.removeItem(BACKOFFICE_TOKEN_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(BACKOFFICE_TOKEN_STORAGE_KEY, token);
}

export function getStoredLoginEmail(): string {
  if (typeof window === "undefined") {
    return "";
  }
  return window.localStorage.getItem(BACKOFFICE_LOGIN_EMAIL_STORAGE_KEY) ?? "";
}

export function setStoredLoginEmail(email: string | null): void {
  if (typeof window === "undefined") {
    return;
  }
  const normalizedEmail = String(email ?? "").trim();
  if (!normalizedEmail) {
    window.localStorage.removeItem(BACKOFFICE_LOGIN_EMAIL_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(BACKOFFICE_LOGIN_EMAIL_STORAGE_KEY, normalizedEmail);
}
