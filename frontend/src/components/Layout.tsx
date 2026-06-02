import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { Search, Bug } from 'lucide-react';
import { useState } from 'react';
import { useDebugMode } from '../lib/debug';

const navItems = [
  { to: '/', label: '工作台', end: true },
  { to: '/targets', label: '标的管理' },
  { to: '/buyers', label: '买家管理' },
  { to: '/recommendations', label: '智能推荐' },
  { to: '/dashboard', label: '数据看板' },
  { to: '/settings', label: '设置' },
];

export default function Layout() {
  const [searchQuery, setSearchQuery] = useState('');
  const navigate = useNavigate();
  const { isAdmin, debugEnabled, toggleDebug } = useDebugMode();

  function handleSearch(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && searchQuery.trim()) {
      navigate(`/targets?q=${encodeURIComponent(searchQuery.trim())}`);
      setSearchQuery('');
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="sticky top-0 z-50 bg-white border-b border-gray-200">
        <div className="max-w-[1440px] mx-auto px-6 flex items-center justify-between h-14">
          <div className="flex items-center gap-8">
            <NavLink to="/" className="flex items-center gap-2">
              <div className="w-7 h-7 bg-brand-600 flex items-center justify-center">
                <span className="text-white font-bold text-xs">M</span>
              </div>
              <span className="text-base font-bold text-gray-900 tracking-tight">Match-MA</span>
            </NavLink>
          </div>

          <div className="flex items-center gap-3">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
              <input
                type="text"
                placeholder="搜索标的/买家/意向..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={handleSearch}
                className="w-56 pl-8 pr-3 py-1.5 text-sm bg-gray-50 border border-gray-200 placeholder:text-gray-400 focus:outline-none focus:border-brand-500 focus:bg-white transition-colors"
              />
            </div>
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 bg-brand-600 flex items-center justify-center text-white text-xs font-semibold">
                张
              </div>
              <span className="text-sm text-gray-700">张三</span>
            </div>
            {isAdmin && (
              <button
                onClick={toggleDebug}
                className={`inline-flex items-center gap-1 px-2 py-1 text-xs font-medium border transition-colors ${
                  debugEnabled
                    ? 'bg-amber-50 text-amber-700 border-amber-200'
                    : 'bg-gray-50 text-gray-500 border-gray-200 hover:border-amber-200 hover:text-amber-600'
                }`}
              >
                <Bug className="w-3 h-3" />
                Debug
              </button>
            )}
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
