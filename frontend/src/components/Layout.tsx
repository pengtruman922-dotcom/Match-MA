import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { ChevronDown, LogOut, Search } from 'lucide-react';
import { useState } from 'react';
import { clearAuthSession, getStoredUser, isAdmin as isAdminRole } from '../lib/auth';

const baseNavItems: Array<{ to: string; label: string; end?: boolean }> = [
  { to: '/', label: '工作台', end: true },
  { to: '/targets', label: '标的管理' },
  { to: '/buyers', label: '买家管理' },
  { to: '/recommendations', label: '智能推荐' },
  { to: '/dashboard', label: '数据看板' },
  { to: '/settings', label: '设置' },
];

const adminNavItems: Array<{ to: string; label: string; end?: boolean }> = [
  { to: '/users', label: '账号管理' },
  { to: '/tasks', label: '任务中心' },
];

export default function Layout() {
  const [searchQuery, setSearchQuery] = useState('');
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const navigate = useNavigate();
  const user = getStoredUser();
  const displayName = normalizedDisplayName(user?.display_name || user?.username || '管理员');
  const avatarText = displayName.slice(0, 3);
  const navItems = isAdminRole() ? [...baseNavItems, ...adminNavItems] : baseNavItems;

  function handleSearch(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && searchQuery.trim()) {
      navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`);
      setSearchQuery('');
    }
  }

  function handleLogout() {
    clearAuthSession();
    navigate('/login', { replace: true });
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="sticky top-0 z-50 bg-white border-b border-gray-200">
        <div className="max-w-[1440px] mx-auto px-6 flex items-center justify-between h-14">
          <div />

          <div className="flex items-center gap-3">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
              <input
                type="text"
                placeholder="搜索标的/买家/意向..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={handleSearch}
                className="w-64 pl-8 pr-3 py-1.5 text-sm bg-gray-50 border border-gray-200 placeholder:text-gray-400 focus:outline-none focus:border-brand-500 focus:bg-white transition-colors"
              />
            </div>
            <div className="relative">
              <button
                type="button"
                onClick={() => setUserMenuOpen((open) => !open)}
                className="flex items-center gap-2 text-sm text-gray-700 hover:text-gray-900"
              >
                <span className="min-w-12 h-7 px-2 bg-red-600 text-white flex items-center justify-center text-xs font-semibold tracking-wide">
                  {avatarText}
                </span>
                <ChevronDown className={`w-3.5 h-3.5 text-gray-400 transition-transform ${userMenuOpen ? 'rotate-180' : ''}`} />
              </button>
              {userMenuOpen && (
                <div className="absolute right-0 mt-2 w-44 bg-white border border-gray-200 shadow-lg py-2">
                  <div className="px-3 pb-2 border-b border-gray-100">
                    <p className="text-sm font-medium text-gray-900 truncate">{displayName}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{user?.role === 'admin' ? '管理员' : user?.role || '用户'}</p>
                  </div>
                  <button
                    type="button"
                    onClick={handleLogout}
                    className="w-full px-3 py-2 text-left text-sm text-gray-600 hover:bg-gray-50 hover:text-red-600 flex items-center gap-2"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    退出登录
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="max-w-[1440px] mx-auto px-6">
          <nav className="flex items-center gap-0.5 -mb-px">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                    isActive
                      ? 'border-brand-600 text-brand-600'
                      : 'border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="max-w-[1440px] mx-auto px-6 py-5">
        <Outlet />
      </main>
    </div>
  );
}

function normalizedDisplayName(value: string): string {
  const trimmed = value.trim();
  if (!trimmed || trimmed === 'Match-MA Admin') return '管理员';
  return trimmed;
}
