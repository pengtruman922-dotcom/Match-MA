import { FormEvent, useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { LockKeyhole, ShieldCheck } from 'lucide-react';
import { auth } from '../lib/api';
import { isLoggedIn, saveAuthSession } from '../lib/auth';

export default function Login() {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname || '/';

  if (isLoggedIn()) {
    return <Navigate to={from} replace />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response = await auth.login({ username: username.trim(), password });
      saveAuthSession(response);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败，请检查账号和密码');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#f7f2ea] text-gray-900 relative overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_15%,rgba(212,0,15,0.12),transparent_28%),radial-gradient(circle_at_85%_20%,rgba(212,160,23,0.16),transparent_26%),linear-gradient(135deg,#fffaf3_0%,#f1eee8_48%,#fff_100%)]" />
      <div className="relative min-h-screen grid lg:grid-cols-[1.05fr_0.95fr]">
        <section className="hidden lg:flex flex-col justify-between p-12">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-brand-600 text-white flex items-center justify-center font-bold">M</div>
            <div>
              <p className="text-lg font-bold tracking-tight">Match-MA</p>
              <p className="text-xs text-gray-500">并购撮合工作台</p>
            </div>
          </div>
          <div className="max-w-xl">
            <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-white/70 border border-white text-xs text-brand-700 mb-6">
              <ShieldCheck className="w-4 h-4" />
              单管理员测试入口
            </div>
            <h1 className="text-5xl font-bold leading-tight tracking-tight">
              先保护线上入口，
              <br />
              再推进真实样本压测。
            </h1>
            <p className="mt-5 text-gray-600 text-base leading-7">
              当前版本使用一个管理员账号登录，暂不引入 team/workspace/role 权限模型。后续正式权限系统上线后，可替换为完整账号体系。
            </p>
          </div>
          <p className="text-xs text-gray-500">API keys and provider secrets stay server-side only.</p>
        </section>

        <section className="flex items-center justify-center px-6 py-12">
          <form onSubmit={handleSubmit} className="w-full max-w-md bg-white border border-gray-200 shadow-xl shadow-gray-200/60 p-8">
            <div className="w-12 h-12 bg-brand-600 text-white flex items-center justify-center mb-6">
              <LockKeyhole className="w-6 h-6" />
            </div>
            <h2 className="text-2xl font-bold tracking-tight">登录 Match-MA</h2>
            <p className="mt-2 text-sm text-gray-500">请输入 Railway 中配置的管理员账号。</p>

            <div className="mt-8 space-y-4">
              <label className="block">
                <span className="block text-sm font-medium text-gray-700 mb-1.5">账号</span>
                <input
                  className="input h-11"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  autoComplete="username"
                  required
                />
              </label>
              <label className="block">
                <span className="block text-sm font-medium text-gray-700 mb-1.5">密码</span>
                <input
                  className="input h-11"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  required
                />
              </label>
            </div>

            {error && <div className="mt-4 px-3 py-2 bg-red-50 text-red-700 text-sm border border-red-100">{error}</div>}

            <button
              type="submit"
              disabled={loading}
              className="mt-6 w-full h-11 bg-brand-600 text-white text-sm font-semibold hover:bg-brand-700 disabled:opacity-60 transition-colors"
            >
              {loading ? '登录中...' : '进入工作台'}
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}
