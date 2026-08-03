export interface AuthUser {
  user_id?: string;
  username: string;
  display_name: string;
  role: string;
  auth_enabled: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

const TOKEN_KEY = 'match_ma_admin_token';
const USER_KEY = 'match_ma_admin_user';

export function getAuthToken(): string | null {
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): AuthUser | null {
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    clearAuthSession();
    return null;
  }
}

export function saveAuthSession(response: LoginResponse): void {
  window.localStorage.setItem(TOKEN_KEY, response.access_token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(response.user));
}

export function clearAuthSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export function isLoggedIn(): boolean {
  return Boolean(getAuthToken());
}

export function isAdmin(): boolean {
  const user = getStoredUser();
  // 前端权限展示也应失败关闭；老会话缺少 role 时重新登录即可恢复。
  return user?.role === 'admin';
}
