"use client";

const API_MUTATION_EVENT = "backoffice:api-mutation";
const API_MUTATION_STORAGE_KEY = "backoffice:api-mutation";

export type ApiMutationDetail = {
  at: number;
  method: string;
  path: string;
};

export function emitApiMutation(detail: Omit<ApiMutationDetail, "at">): void {
  if (typeof window === "undefined") {
    return;
  }

  const payload: ApiMutationDetail = {
    ...detail,
    at: Date.now(),
  };

  window.dispatchEvent(
    new CustomEvent<ApiMutationDetail>(API_MUTATION_EVENT, {
      detail: payload,
    }),
  );

  try {
    window.localStorage.setItem(API_MUTATION_STORAGE_KEY, JSON.stringify(payload));
    window.localStorage.removeItem(API_MUTATION_STORAGE_KEY);
  } catch {
    // Ignore storage errors so UI updates still happen in the current tab.
  }
}

export function subscribeToApiMutations(
  callback: (detail: ApiMutationDetail) => void,
): () => void {
  if (typeof window === "undefined") {
    return () => {};
  }

  const handleMutation = (event: Event) => {
    const customEvent = event as CustomEvent<ApiMutationDetail>;
    if (customEvent.detail) {
      callback(customEvent.detail);
    }
  };

  const handleStorage = (event: StorageEvent) => {
    if (
      event.key !== API_MUTATION_STORAGE_KEY ||
      !event.newValue
    ) {
      return;
    }

    try {
      callback(JSON.parse(event.newValue) as ApiMutationDetail);
    } catch {
      // Ignore malformed payloads.
    }
  };

  window.addEventListener(API_MUTATION_EVENT, handleMutation as EventListener);
  window.addEventListener("storage", handleStorage);

  return () => {
    window.removeEventListener(API_MUTATION_EVENT, handleMutation as EventListener);
    window.removeEventListener("storage", handleStorage);
  };
}
