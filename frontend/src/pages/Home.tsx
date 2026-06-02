import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Plus,
  UserPlus,
  MessageSquarePlus,
  Sparkles,
  ChevronRight,
  AlertCircle,
  CheckCircle2,
  Clock,
} from 'lucide-react';
import { fetchWorkbenchData, type ActionGroup } from '../lib/workbench';
import type { BusinessUpdate } from '../types/api';
import BusinessUpdateDrawer from '../components/BusinessUpdateDrawer';

export default function Home() {
  const [groups, setGroups] = useState<ActionGroup[]>([]);
  const [recentUpdates, setRecentUpdates] = useState<BusinessUpdate[]>([]);
  const [loading, setLoading] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const navigate = useNavigate();

  function load() {
    setLoading(true);
    fetchWorkbenchData()
      .then(({ groups: g, recentUpdates: u }) => {
        setGroups(g);
        setRecentUpdates(u);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  const totalPending = groups.reduce((sum, g) => sum + g.count, 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">工作台</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })}
        </p>
      </div>

      <div className="grid grid-cols-12 gap-5">
        {/* Left: Pending + Recent */}
        <div className="col-span-8 space-y-5">
          {/* Pending Actions - grouped */}
          <div className="bg-white border border-gray-200">
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-gray-900">待我处理</h2>
                {totalPending > 0 && (
                  <span className="text-xs bg-red-50 text-red-600 px-1.5 py-0.5 font-medium">
                    {totalPending}
                  </span>
                )}
              </div>
            </div>

            {loading ? (
              <LoadingPlaceholder />
            ) : groups.length === 0 ? (
              <div className="px-5 py-10 text-center">
                <CheckCircle2 className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
                <p className="text-sm text-gray-500">暂无待处理事项</p>
              </div>
            ) : (
              <div className="divide-y divide-gray-100">
                {groups.map((group) => (
                  <GroupSection key={group.key} group={group} />
                ))}
              </div>
            )}
          </div>

          {/* Recent Activity */}
          <div className="bg-white border border-gray-200">
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
              <h2 className="text-sm font-semibold text-gray-900">最近动态</h2>
              <Link
                to="/updates"
                className="text-xs text-brand-600 hover:text-brand-700 font-medium flex items-center gap-0.5"
              >
                查看全部 <ChevronRight className="w-3 h-3" />
              </Link>
            </div>
            {loading ? (
              <LoadingPlaceholder />
            ) : recentUpdates.length === 0 ? (
              <p className="text-sm text-gray-400 py-6 text-center">暂无动态</p>
            ) : (
              <div className="divide-y divide-gray-100">
                {recentUpdates.slice(0, 5).map((update) => (
                  <div key={update.id} className="px-5 py-3 flex items-start gap-3 hover:bg-gray-50 transition-colors">
                    <Clock className="w-3.5 h-3.5 text-gray-400 mt-0.5 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-400 font-mono">
                          {new Date(update.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                        </span>
                        <span className={`text-xs px-1.5 py-0.5 font-medium ${
                          update.processing_status === 'pending' ? 'bg-amber-50 text-amber-700' :
                          update.processing_status === 'parsed' ? 'bg-blue-50 text-blue-700' :
                          update.processing_status === 'applied' ? 'bg-emerald-50 text-emerald-700' :
                          'bg-gray-100 text-gray-600'
                        }`}>
                          {update.processing_status === 'applied' ? '已应用' :
                           update.processing_status === 'parsed' ? '已解析' :
                           update.processing_status === 'pending' ? '处理中' :
                           update.processing_status}
                        </span>
                      </div>
                      <p className="text-sm text-gray-700 mt-0.5 line-clamp-1">{update.raw_text}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right sidebar */}
        <div className="col-span-4 space-y-5">
          {/* Quick Actions */}
          <div className="bg-white border border-gray-200 p-5">
            <h2 className="text-sm font-semibold text-gray-900 mb-3">快速操作</h2>
            <div className="space-y-2">
              <QuickAction icon={Plus} label="新建标的" onClick={() => navigate('/targets/new')} />
              <QuickAction icon={UserPlus} label="新建买家意向" onClick={() => navigate('/buyers?action=new-intent')} />
              <QuickAction icon={MessageSquarePlus} label="录入业务更新" onClick={() => setDrawerOpen(true)} />
              <QuickAction icon={Sparkles} label="发起推荐" onClick={() => navigate('/recommendations')} />
            </div>
          </div>

          {/* Weekly Stats */}
          <div className="bg-white border border-gray-200 p-5">
            <h2 className="text-sm font-semibold text-gray-900 mb-3">本周概览</h2>
            <div className="space-y-2.5">
              <StatRow label="待复核" value={totalPending} highlight />
              <StatRow label="最近业务更新" value={recentUpdates.length} />
            </div>
            <p className="text-xs text-gray-400 mt-3">更多统计数据后端开发中</p>
          </div>

          {/* Recent Recommendation Sessions */}
          <div className="bg-white border border-gray-200 p-5">
            <h2 className="text-sm font-semibold text-gray-900 mb-3">最近推荐会话</h2>
            <p className="text-xs text-gray-400">推荐会话记录后端开发中</p>
          </div>
        </div>
      </div>

      <BusinessUpdateDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onSuccess={() => load()}
      />
    </div>
  );
}

function GroupSection({ group }: { group: ActionGroup }) {
  return (
    <div className="px-5 py-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <AlertCircle className="w-3.5 h-3.5 text-amber-500" />
          <span className="text-sm font-medium text-gray-800">{group.label}</span>
        </div>
        <span className="text-xs font-medium text-gray-500 bg-gray-100 px-1.5 py-0.5">
          {group.count}
        </span>
      </div>
      <div className="space-y-0.5 ml-5.5">
        {group.items.slice(0, 3).map((item) => (
          <div key={item.id} className="flex items-center justify-between py-1.5 group cursor-pointer hover:bg-gray-50 -mx-2 px-2">
            <div className="min-w-0 flex-1">
              <span className="text-sm text-gray-600 line-clamp-1">
                {item.raw_evidence_text?.slice(0, 60) || '更新内容'}
              </span>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-xs text-gray-400">
                {new Date(item.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
              </span>
              <ChevronRight className="w-3.5 h-3.5 text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity" />
            </div>
          </div>
        ))}
        {group.count > 3 && (
          <Link to="/updates" className="text-xs text-brand-600 hover:text-brand-700 font-medium py-1 block">
            查看全部 {group.count} 项
          </Link>
        )}
      </div>
    </div>
  );
}

function QuickAction({ icon: Icon, label, onClick }: { icon: typeof Plus; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-2.5 px-3.5 py-2.5 border border-gray-200 bg-white text-gray-800 text-sm font-medium transition-all hover:border-brand-500 hover:text-brand-600 hover:bg-brand-50 active:scale-[0.98]"
    >
      <Icon className="w-4 h-4" />
      {label}
    </button>
  );
}

function StatRow({ label, value, highlight }: { label: string; value: number; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-gray-600">{label}</span>
      <span className={`text-sm font-semibold font-mono ${highlight && value > 0 ? 'text-red-600' : 'text-gray-900'}`}>
        {value}
      </span>
    </div>
  );
}

function LoadingPlaceholder() {
  return (
    <div className="flex items-center justify-center py-10">
      <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}
