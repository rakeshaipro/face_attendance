import type { Envelope } from "./types";

/** Thrown when the backend returns an error envelope or a non-2xx status. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

// --- API key handling ---------------------------------------------------
// Stored in localStorage by Login. Read here so fetch wrappers stay plain
// functions (no React context coupling).
const API_KEY_STORAGE = "fa_api_key";

export function getApiKey(): string | null {
  return localStorage.getItem(API_KEY_STORAGE);
}

export function setApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE, key);
}

export function clearApiKey(): void {
  localStorage.removeItem(API_KEY_STORAGE);
}

// Subscriber notified on 401 so the AuthContext can force-logout.
let onUnauthorized: (() => void) | null = null;
export function registerUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

// --- Core request -------------------------------------------------------
async function request<T>(
  method: string,
  path: string,
  opts: { body?: unknown; params?: Record<string, unknown>; signal?: AbortSignal } = {},
): Promise<T> {
  const url = buildUrl(path, opts.params as Record<string, string | number | boolean | null | undefined> | undefined);
  const key = getApiKey();
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;

  if (opts.body instanceof FormData) {
    body = opts.body;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  if (key) headers["X-API-Key"] = key;

  let resp: Response;
  try {
    resp = await fetch(url, { method, headers, body, signal: opts.signal });
  } catch (e) {
    throw new ApiError(0, e instanceof Error ? e.message : "Network error");
  }

  if (resp.status === 401 || resp.status === 403) {
    if (resp.status === 401 && onUnauthorized) onUnauthorized();
  }

  // File/binary responses — caller handles blob/text.
  const contentType = resp.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    if (!resp.ok) throw new ApiError(resp.status, resp.statusText);
    return resp as unknown as T;
  }

  const envelope = (await resp.json()) as Envelope<T>;
  if (!envelope.success) {
    throw new ApiError(resp.status, envelope.error || `Request failed (${resp.status})`);
  }
  if (resp.status === 401 && onUnauthorized) onUnauthorized();
  return envelope.data as T;
}

function buildUrl(path: string, params?: Record<string, unknown>): string {
  if (!params) return path;
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const qs = sp.toString();
  return qs ? `${path}?${qs}` : path;
}

// --- Public helpers -----------------------------------------------------
export const api = {
  get: <T>(path: string, params?: Record<string, unknown>, signal?: AbortSignal) =>
    request<T>("GET", path, { params, signal }),
  post: <T>(path: string, body?: unknown) =>
    request<T>("POST", path, { body }),
  put: <T>(path: string, body?: unknown) =>
    request<T>("PUT", path, { body }),
  del: <T>(path: string, params?: Record<string, unknown>) =>
    request<T>("DELETE", path, { params }),
  upload: <T>(path: string, file: Blob | File, filename = "frame.jpg", params?: Record<string, unknown>) => {
    const fd = new FormData();
    fd.append("file", file, filename);
    return request<T>("POST", path, { body: fd, params });
  },
  /** Download a file (snapshot, CSV export). Returns a Blob. */
  download: async (path: string): Promise<Blob> => {
    const key = getApiKey();
    const headers: Record<string, string> = {};
    if (key) headers["X-API-Key"] = key;
    const resp = await fetch(path, { headers });
    if (!resp.ok) throw new ApiError(resp.status, resp.statusText);
    return resp.blob();
  },
};
