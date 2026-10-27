
const API_BASE_URL = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");

let csrf = "";
export const setCsrf = (t: string) => {
  csrf = t;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  opts: {
    method?: string;
    body?: unknown;
    form?: FormData;
    headers?: Record<string, string>;
  } = {}
): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };

  if (method !== "GET") headers["X-CSRF-Token"] = csrf;

  let body: BodyInit | undefined;

  if (opts.form) {
    body = opts.form;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const url = `${API_BASE_URL}${normalizedPath}`;

  let res: Response;

  try {
    res = await fetch(url, {
      method,
      headers,
      body,
      credentials: "include",
    });
  } catch {
    throw new ApiError(
      0,
      "No se pudo conectar con el servidor. Revisa tu conexión."
    );
  }

  if (res.status === 204) return undefined as T;

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    const d = (data as { detail?: unknown }).detail;

    const msg =
      typeof d === "string"
        ? d
        : Array.isArray(d)
          ? d.map((e: { msg?: string }) => e.msg).join(". ")
          : d && typeof d === "object" && "message" in d
            ? String((d as { message: string }).message)
            : "Ocurrió un error";

    throw new ApiError(res.status, msg);
  }

  return data as T;
}

export const usd = (v: string | number) =>
  Number(v).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
  });

