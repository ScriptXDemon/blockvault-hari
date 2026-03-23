const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export function getApiBase() {
  return API_BASE.replace(/\/+$/, "");
}

async function readErrorMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.clone().json()) as { detail?: unknown; message?: unknown };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (typeof payload.message === "string") {
      return payload.message;
    }
    if (payload.detail) {
      return JSON.stringify(payload.detail);
    }
  } catch {
    // Ignore JSON parsing failures and fall back to plain text.
  }

  const text = await response.text();
  return text || fallback;
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBase()}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, `Request failed with ${response.status}`));
  }

  return (await response.json()) as T;
}

export async function apiUpload<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(`${getApiBase()}${path}`, {
    method: "POST",
    credentials: "include",
    body,
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, `Upload failed with ${response.status}`));
  }

  return (await response.json()) as T;
}

export async function apiBinary(path: string): Promise<Response> {
  const response = await fetch(`${getApiBase()}${path}`, {
    credentials: "include",
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, `Binary request failed with ${response.status}`));
  }

  return response;
}
