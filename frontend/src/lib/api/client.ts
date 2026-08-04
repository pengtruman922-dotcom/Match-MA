const DEFAULT_API_BASE_URL = 'https://match-ma-production.up.railway.app/api/v1';

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL;

function authHeaders(): Record<string, string> {
  const token = window.localStorage.getItem('match_ma_admin_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function buildQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  }
  const query = search.toString();
  return query ? `?${query}` : '';
}

export async function apiRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const isFormData = typeof FormData !== 'undefined' && options?.body instanceof FormData;
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
        ...authHeaders(),
        ...options?.headers,
      },
    });
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'unknown network error';
    throw new Error(
      `${reason}：请求在收到后端响应前失败。请先重试；若持续失败，可检查当前网络与 Railway 部署状态。`,
    );
  }

  if (!response.ok) {
    const errorText = await response.text();
    if (response.status === 401) {
      window.localStorage.removeItem('match_ma_admin_token');
      window.localStorage.removeItem('match_ma_admin_user');
      if (window.location.pathname !== '/login') {
        window.location.assign('/login');
      }
    }
    throw new Error(`API ${response.status}: ${errorText}`);
  }

  if (response.status === 204) {
    return { status: 'ok' } as T;
  }

  return response.json() as Promise<T>;
}

export interface ApiStreamEvent {
  event: string;
  data: Record<string, unknown>;
}

/**
 * Read a text/event-stream endpoint.
 *
 * Not `EventSource`: that API cannot send an Authorization header, and every
 * endpoint here is bearer-authenticated. Reading the body with fetch keeps the
 * same auth path as every other call.
 */
export async function* apiEventStream(
  path: string,
  options?: { signal?: AbortSignal },
): AsyncGenerator<ApiStreamEvent> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: 'text/event-stream', ...authHeaders() },
    signal: options?.signal,
  });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`);
  }
  if (!response.body) {
    throw new Error('当前浏览器不支持流式响应');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // 事件以空行分隔；最后一段可能只收到一半，留在 buffer 里等下一个 chunk。
      let separator = buffer.indexOf('\n\n');
      while (separator !== -1) {
        const rawEvent = buffer.slice(0, separator);
        buffer = buffer.slice(separator + 2);
        const parsed = parseSseEvent(rawEvent);
        if (parsed) yield parsed;
        separator = buffer.indexOf('\n\n');
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function parseSseEvent(raw: string): ApiStreamEvent | null {
  let event = 'message';
  const dataLines: string[] = [];
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) as Record<string, unknown> };
  } catch {
    return null;
  }
}

export async function apiBlobResponse(path: string, options?: RequestInit): Promise<Response> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      ...authHeaders(),
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const errorText = await response.text();
    let detail = errorText;
    try {
      const payload = JSON.parse(errorText) as { detail?: string };
      detail = payload.detail || errorText;
    } catch {
      // Keep the original response text when the API did not return JSON.
    }
    throw new Error(`API ${response.status}: ${detail}`);
  }

  return response;
}
