import "server-only";
import { cookies } from "next/headers";

const BACKEND_URL = process.env.BACKEND_API_URL ?? "http://127.0.0.1:8000";
export const TOKEN_COOKIE = "orion_token";

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; message: string };

/**
 * Server-only fetch wrapper against the real FastAPI backend. Every page
 * and Server Action goes through this - the JWT never reaches client-side
 * JS (it lives in an httpOnly cookie), and every backend error is turned
 * into a typed result instead of a raw exception a page could accidentally
 * render (see docs/frontend-architecture.md's error-handling section).
 */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit & { token?: string }
): Promise<ApiResult<T>> {
  const token = init?.token ?? (await cookies()).get(TOKEN_COOKIE)?.value;

  let response: Response;
  try {
    response = await fetch(`${BACKEND_URL}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch {
    return { ok: false, status: 0, message: "The Orion API is unreachable. Is the backend running?" };
  }

  if (response.status === 204) {
    return { ok: true, data: undefined as T };
  }

  let body: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }

  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : `Request failed (${response.status})`;
    return { ok: false, status: response.status, message: detail };
  }

  return { ok: true, data: body as T };
}

export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  return apiFetch<T>(path, { method: "GET" });
}

export async function apiPost<T>(path: string, body?: unknown): Promise<ApiResult<T>> {
  return apiFetch<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });
}

/** Unwraps an ApiResult for Server Components that should 404/error-boundary
 * on failure rather than render a partial page - use apiGet directly (and
 * handle the ok:false case explicitly) whenever the page has a more
 * specific, useful thing to show than a generic error boundary. */
export function unwrap<T>(result: ApiResult<T>): T {
  if (!result.ok) {
    throw new Error(result.message);
  }
  return result.data;
}
