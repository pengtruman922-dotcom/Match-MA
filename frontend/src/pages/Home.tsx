import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Clock,
  MessageSquarePlus,
  Plus,
  Sparkles,
  UserPlus,
} from 'lucide-react';
import { fetchWorkbenchData, type ActionGroup } from '../lib/workbench';
import type { ExtractedAction, WorkbenchActivity, WorkbenchOverview } from '../types/api';
import BusinessUpdateDrawer from '../components/BusinessUpdateDrawer';
import BackgroundJobFailurePanel from '../components/BackgroundJobFailurePanel';
import { useDebugMode } from '../lib/debug';

export default function Home() {
  const [groups, setGroups] = useState<ActionGroup[]>([]);
  const [recentActivity, setRecentActivity] = useState<WorkbenchActivity[]>([]);
  const [overview, setOverview] = useState<WorkbenchOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const navigate = useNavigate();
  const { debugEnabled } = useDebugMode();

  function load() {
    setLoading(true);
    fetchWorkbenchData()
      .then((data) => {
        setGroups(data.groups);
        setRecentActivity(data.recentActivity);
        setOverview(data.overview);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  const totalPending = groups.reduce((sum, group) => sum + group.count, 0);

  return (
    <div className="grid grid-cols-12 gap-5">
      <div className="col-span-8 space-y-5">
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
            <Link to="/updates" className="text-xs text-brand-600 hover:text-brand-700 font-medium flex items-center gap-0.5">
              查看全部 <ChevronRight className="w-3 h-3" />
            </Link>
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
                <GroupSection key={group.key} group={group} onOpenAction={openAction} />
              ))}
            </div>
          )}
        </div>

        <div className="bg-white border border-gray-200">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900">最近动态</h2>
            <Link to="/updates" className="text-xs text-brand-600 hover:text-brand-700 font-medium flex items-center gap-0.5">
              查看全部 <ChevronRight className="w-3 h-3" />
            </Link>
          </div>
          {loading ? (
            <LoadingPlaceholder />
          ) : recentActivity.length === 0 ? (
            <p className="text-sm text-gray-400 py-6 text-center">暂无动态</p>
          ) : (
            <div className="divide-y divide-gray-100">
              {recentActivity.slice(0, 8).map((activity) => (
                <button
                  key={`${activity.activity_type}-${activity.entity_id}`}
                  type="button"
                  onClick={() => activity.route && navigate(activity.route)}
                  className="w-full text-left px-5 py-3 flex items-start gap-3 hover:bg-gray-50 transition-colors"
                >
                  <Clock className="w-3.5 h-3.5 text-gray-400 mt-0.5 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <ActivityBadge label={activity.activity_label || activity.activity_type} status={activity.status} />
                      <span className="text-xs text-gray-400 font-mono">{formatDateTime(activity.happened_at)}</span>
                    </div>
                    <p className="text-sm text-gray-800 mt-1 line-clamp-1">{activity.title || buildActivityTitle(activity)}</p>
                    {activity.subtitle && <p className="text-xs text-gray-500 mt-0.5 line-clamp-1">{activity.subtitle}</p>}
                  </div>
                  {activity.route && <ChevronRight className="w-3.5 h-3.5 text-gray-300 mt-1" />}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="col-span-4 space-y-5">
        <div className="bg-white border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">快捷操作</h2>
          <div className="space-y-2">
            <QuickAction icon={Plus} label="新建标的" onClick={() => navigate('/targets?action=new')} />
            <QuickAction icon={UserPlus} label="新建买家意向" onClick={() => navigate('/buyers?action=new-intent')} />
            <QuickAction icon={MessageSquarePlus} label="录入业务更新" onClick={() => setDrawerOpen(true)} />
            <QuickAction icon={Sparkles} label="智能推荐" onClick={() => navigate('/recommendations')} />
          </div>
        </div>

        <div className="bg-white border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">本周概览</h2>
          <div className="space-y-2.5">
            <StatRow label="新增标的" value={numberValue(overview?.weekly_new_target_count)} />
            <StatRow label="新增买家意向" value={numberValue(overview?.weekly_new_buyer_intent_count)} />
            <StatRow label="更新标的" value={numberValue(overview?.weekly_updated_target_count)} />
            <StatRow label="更新动态" value={numberValue(overview?.weekly_business_update_count ?? overview?.recent_update_count)} />
          </div>
        </div>

        {debugEnabled && <BackgroundJobFailurePanel />}

        <div className="bg-white border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">使用提示</h2>
          <p className="text-xs text-gray-400">可从快捷操作录入自然语言更新，系统会拆解为待复核动作。</p>
        </div>
      </div>

      <BusinessUpdateDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} onSuccess={() => load()} />
    </div>
  );

  function openAction(action: ExtractedAction) {
    const baseRoute = action.review_route || `/updates/${action.business_update_id}`;
    navigate(`${baseRoute}${baseRoute.includes('?') ? '&' : '?'}actionId=${action.id}`);
  }
}

function GroupSection({ group, onOpenAction }: { group: ActionGroup; onOpenAction: (action: ExtractedAction) => void }) {
  const [expanded, setExpanded] = useState(false);
  const visibleItems = expanded ? group.items : group.items.slice(0, 3);
  return (
    <div className="px-5 py-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <AlertCircle className="w-3.5 h-3.5 text-amber-500" />
          <span className="text-sm font-medium text-gray-800">{group.label}</span>
        </div>
        <span className="text-xs font-medium text-gray-500 bg-gray-100 px-1.5 py-0.5">{group.count}</span>
      </div>
      <div className="space-y-1 ml-5.5 max-h-80 overflow-y-auto scrollbar-thin">
        {visibleItems.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onOpenAction(item)}
            className="w-full flex items-center justify-between py-2 group cursor-pointer hover:bg-gray-50 -mx-2 px-2 text-left"
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm text-gray-800 line-clamp-1">{item.task_title || actionTypeLabel(item.action_type)}</p>
              <p className="text-xs text-gray-500 mt-0.5 line-clamp-1">{item.task_subtitle || item.raw_evidence_text || '暂无摘要'}</p>
            </div>
            <div className="flex items-center gap-2 shrink-0 ml-3">
              <span className="text-xs text-gray-400">{formatDateTime(item.created_at)}</span>
              <ChevronRight className="w-3.5 h-3.5 text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity" />
            </div>
          </button>
        ))}
        {group.count > 3 && (
          <div className="flex items-center gap-3 pt-1">
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="text-xs text-brand-600 hover:text-brand-700 font-medium inline-flex items-center gap-1"
            >
              {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              {expanded ? '收起' : `展开全部 ${group.count} 条`}
            </button>
            <Link to="/updates" className="text-xs text-gray-500 hover:text-brand-700 font-medium">去复核页</Link>
          </div>
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

function StatRow({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-gray-600">{label}</span>
      <span className="text-sm font-semibold font-mono text-gray-900">{value}</span>
    </div>
  );
}

function ActivityBadge({ label, status }: { label: string; status: string }) {
  const tone = status === 'failed' ? 'bg-red-50 text-red-700' : status === 'parsed' ? 'bg-blue-50 text-blue-700' : 'bg-gray-100 text-gray-600';
  return <span className={`text-xs px-1.5 py-0.5 font-medium ${tone}`}>{label}</span>;
}

function LoadingPlaceholder() {
  return (
    <div className="flex items-center justify-center py-10">
      <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function numberValue(value: unknown): number {
  return typeof value === 'number' ? value : 0;
}

function buildActivityTitle(activity: WorkbenchActivity): string {
  const label = activity.activity_label || '更新';
  const name = activity.object_name || '未命名对象';
  return `${label}：${name}`;
}

function actionTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    seller_fact_update: '标的信息更新',
    seller_event: '标的事件更新',
    buyer_intent_update: '买家/意向更新',
    buyer_seller_relation_update: '推荐关系更新',
    buyer_intent_target_exclusion: '排除标的',
    unresolved_item: '待人工判断',
  };
  return labels[type] || '待处理';
}
