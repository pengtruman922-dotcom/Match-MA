import { useCallback, useEffect, useState } from 'react';
import { KeyRound, Loader2, Plus, ShieldCheck, UserRound, X } from 'lucide-react';
import { users } from '../lib/api';
import type { AppUser, AppUserCreate } from '../types/api';
import { isAdmin } from '../lib/auth';

const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  consultant: '顾问',
  manager: '经理',
  developer: '系统',
};

const EMPTY_FORM: AppUserCreate = { username: '', name: '', password: '', role: 'consultant' };

/** 从未动过手的账号显示「—」，而不是一个假的时间。 */
function formatActivity(value: string | null): string {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 16);
  return parsed.toLocaleString('zh-CN', {
    year: '2-digit',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function Users() {
  const [items, setItems] = useState<AppUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<AppUserCreate>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [actionUserId, setActionUserId] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    users
      .list()
      .then((rows) => {
        setItems(rows);
        setError(null);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (!isAdmin()) {
    return (
      <div className="p-8 text-sm text-gray-500">仅管理员可以访问账号管理。</div>
    );
  }

  const handleCreate = async () => {
    if (!form.username.trim() || !form.name.trim() || form.password.length < 6) {
      setError('请填写用户名、姓名，密码至少 6 位。');
      return;
    }
    setSaving(true);
    try {
      await users.create({ ...form, username: form.username.trim(), name: form.name.trim() });
      setShowCreate(false);
      setForm(EMPTY_FORM);
      setError(null);
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleResetPassword = async (user: AppUser) => {
    const password = window.prompt(`为「${user.name}」设置新密码（至少 6 位）：`);
    if (!password) return;
    if (password.length < 6) {
      window.alert('密码至少 6 位。');
      return;
    }
    setActionUserId(user.id);
    try {
      await users.resetPassword(user.id, password);
      window.alert('密码已重置。');
    } catch (err) {
      window.alert(`重置失败：${(err as Error).message}`);
    } finally {
      setActionUserId(null);
    }
  };

  const handleToggleStatus = async (user: AppUser) => {
    const nextStatus = user.status === 'active' ? 'disabled' : 'active';
    if (nextStatus === 'disabled' && !window.confirm(`确定停用「${user.name}」？停用后该账号将无法登录。`)) {
      return;
    }
    setActionUserId(user.id);
    try {
      await users.update(user.id, { status: nextStatus });
      load();
    } catch (err) {
      window.alert(`操作失败：${(err as Error).message}`);
    } finally {
      setActionUserId(null);
    }
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">账号管理</h1>
          <p className="mt-1 text-sm text-gray-500">创建团队账号、重置密码、停用账号。新建的标的和买家默认归创建人负责。</p>
        </div>
        <button
          type="button"
          onClick={() => setShowCreate((value) => !value)}
          className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          {showCreate ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
          {showCreate ? '取消' : '新建账号'}
        </button>
      </div>

      {error && <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>}

      {showCreate && (
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-sm text-gray-600">
              用户名（登录用）
              <input
                value={form.username}
                onChange={(event) => setForm({ ...form, username: event.target.value })}
                placeholder="如 zhangsan"
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="text-sm text-gray-600">
              姓名
              <input
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                placeholder="如 张三"
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="text-sm text-gray-600">
              初始密码
              <input
                type="password"
                value={form.password}
                onChange={(event) => setForm({ ...form, password: event.target.value })}
                placeholder="至少 6 位"
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="text-sm text-gray-600">
              角色
              <select
                value={form.role}
                onChange={(event) => setForm({ ...form, role: event.target.value as AppUserCreate['role'] })}
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="consultant">顾问（只管理自己负责的数据）</option>
                <option value="admin">管理员（全部数据 + 指派）</option>
              </select>
            </label>
          </div>
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              onClick={handleCreate}
              disabled={saving}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}
              创建
            </button>
          </div>
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
        {loading ? (
          <div className="flex items-center gap-2 p-6 text-sm text-gray-500">
            <Loader2 className="h-4 w-4 animate-spin" /> 加载中...
          </div>
        ) : (
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-4 py-3">账号</th>
                <th className="px-4 py-3">角色</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3">负责标的</th>
                <th className="px-4 py-3">负责买家</th>
                <th className="px-4 py-3">负责意向</th>
                <th className="px-4 py-3" title="最近一次业务更新 / 推进动态 / 字段应用 / 推荐提问，不含 AI 自动回填">
                  最近活跃
                </th>
                <th className="px-4 py-3">创建时间</th>
                <th className="px-4 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.map((user) => (
                <tr key={user.id} className={user.status === 'disabled' ? 'bg-gray-50 text-gray-400' : ''}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {user.role === 'admin' ? (
                        <ShieldCheck className="h-4 w-4 text-blue-600" />
                      ) : (
                        <UserRound className="h-4 w-4 text-gray-400" />
                      )}
                      <div>
                        <div className="font-medium text-gray-900">{user.name}</div>
                        <div className="text-xs text-gray-400">{user.username || '—'}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3">{ROLE_LABELS[user.role] || user.role}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                        user.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-500'
                      }`}
                    >
                      {user.status === 'active' ? '启用' : '已停用'}
                    </span>
                  </td>
                  <td className="px-4 py-3">{user.owned_seller_targets}</td>
                  <td className="px-4 py-3">{user.owned_buyer_parties}</td>
                  <td className="px-4 py-3">{user.owned_buyer_intents}</td>
                  <td className="px-4 py-3 text-xs text-gray-500">{formatActivity(user.latest_activity_at)}</td>
                  <td className="px-4 py-3 text-xs text-gray-400">{user.created_at.slice(0, 10)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => handleResetPassword(user)}
                        disabled={actionUserId === user.id}
                        className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                      >
                        <KeyRound className="h-3.5 w-3.5" /> 重置密码
                      </button>
                      <button
                        type="button"
                        onClick={() => handleToggleStatus(user)}
                        disabled={actionUserId === user.id}
                        className={`rounded-lg border px-2 py-1 text-xs disabled:opacity-50 ${
                          user.status === 'active'
                            ? 'border-red-200 text-red-600 hover:bg-red-50'
                            : 'border-emerald-200 text-emerald-600 hover:bg-emerald-50'
                        }`}
                      >
                        {user.status === 'active' ? '停用' : '启用'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-sm text-gray-400">
                    暂无账号，点击右上角“新建账号”。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
