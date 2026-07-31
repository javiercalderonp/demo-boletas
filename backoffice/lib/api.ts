import { emitApiMutation } from "@/lib/api-events";

const DEFAULT_LOCAL_API_BASE_URL = "http://localhost:8000/api";
const DEFAULT_REQUEST_TIMEOUT_MS = 20000;
const DEFAULT_UPLOAD_TIMEOUT_MS = 60000;
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

    throw new Error("NEXT_PUBLIC_API_BASE_URL must be configured outside local development");
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

type ApiErrorItem = {
  msg?: unknown;
  message?: unknown;
};

function apiErrorMessage(value: unknown, fallback: string): string {
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  if (Array.isArray(value)) {
    const messages = value
      .map((item) => apiErrorMessage(item, ""))
      .filter((message) => message.length > 0);
    return messages.length > 0 ? messages.join(" ") : fallback;
  }
  if (value && typeof value === "object") {
    const item = value as ApiErrorItem;
    return apiErrorMessage(item.msg ?? item.message, fallback);
  }
  return fallback;
}

async function responseErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const data: unknown = await response.json();
    if (data && typeof data === "object" && "detail" in data) {
      return apiErrorMessage((data as { detail?: unknown }).detail, fallback);
    }
    return apiErrorMessage(data, fallback);
  } catch {
    return fallback;
  }
}

async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("La API tardó demasiado en responder. Intenta nuevamente.");
    }
    throw new Error("No se pudo conectar con la API. Revisa tu conexión e intenta nuevamente.");
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export async function apiRequest<T>(
  path: string,
  { method = "GET", body, token }: RequestOptions = {},
): Promise<T> {
  const apiBaseUrl = getApiBaseUrl();
  const normalizedMethod = method.toUpperCase();
  let response: Response;

  try {
    response = await fetchWithTimeout(`${apiBaseUrl}${path}`, {
      method: normalizedMethod,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    }, DEFAULT_REQUEST_TIMEOUT_MS);
  } catch (error) {
    throw error instanceof Error ? error : new Error("No se pudo conectar con la API.");
  }

  if (!response.ok) {
    throw new Error(
      await responseErrorMessage(response, "No se pudo completar la solicitud."),
    );
  }

  if (normalizedMethod !== "GET" && normalizedMethod !== "HEAD") {
    emitApiMutation({ method: normalizedMethod, path });
  }

  return response.json() as Promise<T>;
}

export async function apiUpload<T>(
  path: string,
  formData: FormData,
  token: string,
): Promise<T> {
  const apiBaseUrl = getApiBaseUrl();
  let response: Response;
  try {
    response = await fetchWithTimeout(`${apiBaseUrl}${path}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
      cache: "no-store",
    }, DEFAULT_UPLOAD_TIMEOUT_MS);
  } catch (error) {
    throw error instanceof Error ? error : new Error("No se pudo conectar con la API.");
  }
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, "No se pudo subir el archivo."));
  }
  emitApiMutation({ method: "POST", path });
  return response.json() as Promise<T>;
}

export async function downloadApiCsv(
  path: string,
  token: string,
  filename: string,
): Promise<void> {
  const response = await fetchWithTimeout(
    `${getApiBaseUrl()}${path}`,
    {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    },
    DEFAULT_REQUEST_TIMEOUT_MS,
  );
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response, "No se pudo descargar el archivo."));
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
  } finally {
    URL.revokeObjectURL(url);
  }
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

export async function downloadApiFile(
  path: string,
  token: string,
  filename: string,
): Promise<void> {
  const result = await apiRequest<{ download_url: string }>(path, { token });
  const anchor = document.createElement("a");
  anchor.href = result.download_url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}
