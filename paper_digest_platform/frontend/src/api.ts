const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  token?: string;
}

export async function apiRequest<T>(
  path: string,
  { method = "GET", body, token = "" }: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(`${API_PREFIX}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  const rawText = await response.text();
  let parsed: Record<string, unknown> = {};
  if (rawText) {
    try {
      parsed = JSON.parse(rawText) as Record<string, unknown>;
    } catch {
      parsed = { message: rawText };
    }
  }

  if (!response.ok) {
    const detail = String(parsed.detail ?? parsed.message ?? `请求失败 (${response.status})`);
    throw new ApiError(detail, response.status);
  }
  return parsed as T;
}

