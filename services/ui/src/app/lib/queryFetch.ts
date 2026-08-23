import { apiFetch } from "./auth";

/**
 * Thin JSON-fetching helper for TanStack Query `queryFn`/`mutationFn` callbacks.
 *
 * This wraps `apiFetch` (see `./auth.tsx`) rather than replacing it — `apiFetch`
 * owns auth-header injection and stays the single source of truth for that.
 * This helper only adds the response-parsing/error-shaping boilerplate that
 * every query/mutation function in the app was hand-rolling before TanStack
 * Query landed.
 */
export class ApiQueryError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiQueryError";
    this.status = status;
  }
}

function detailMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && typeof (body as { detail?: unknown }).detail === "string") {
    return (body as { detail: string }).detail;
  }
  return fallback;
}

export async function fetchJson<T>(
  url: string,
  init?: RequestInit,
  fallbackErrorMessage = "Request failed"
): Promise<T> {
  const response = await apiFetch(url, init);
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiQueryError(detailMessage(body, `${fallbackErrorMessage} (${response.status}).`), response.status);
  }
  return body as T;
}
