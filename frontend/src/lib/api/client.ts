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
    throw new Error(`无法连接后端服务（${reason}）。请检查 Railway 部署状态后重试。`);
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
