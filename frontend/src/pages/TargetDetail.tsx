import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Sparkles,
  MessageSquarePlus,
  Search as SearchIcon,
  AlertCircle,
  FileText,
  Clock,
} from 'lucide-react';
import { sellerTargets, updateLogs } from '../lib/api';
import type { SellerTarget, UpdateLog } from '../types/api';
import BusinessUpdateDrawer from '../components/BusinessUpdateDrawer';

type Tab = 'info' | 'attachments' | 'relations' | 'history';

export default function TargetDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [target, setTarget] = useState<SellerTarget | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>('info');
  const [logs, setLogs] = useState<UpdateLog[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    sellerTargets.get(id)
      .then(setTarget)
      .catch(() => navigate('/targets'))
      .finally(() => setLoading(false));
    updateLogs.list({ entity_type: 'seller_target', entity_id: id })
      .then(setLogs)
      .catch(() => {});
  }, [id, navigate]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!target) return null;

  const tabs: { key: Tab; label: string }[] = [
    { key: 'info', label: '基本信息' },
    { key: 'attachments', label: '附件与证据' },
    { key: 'relations', label: '关系/跟进' },
    { key: 'history', label: '更新记录' },
  ];

  return (
    <div className="space-y-5">
      {/* Breadcrumb + actions */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/targets" className="p-1.5 text-gray-400 hover:text-gray-600">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-lg font-semibold text-gray-900">{target.target_name}</h1>
            <p className="text-xs text-gray-500 mt-0.5 flex items-center gap-2 flex-wrap">
              {target.industry_primary && <span>{target.industry_primary}</span>}
              {target.headquarter_province && <span>· {target.headquarter_province}{target.headquarter_city || ''}</span>}
              {target.current_net_profit_yuan && <span>· 利润{formatYuan(target.current_net_profit_yuan)}</span>}
              {target.pe_ratio && <span>· PE{Number(target.pe_ratio).toFixed(1)}</span>}
              <StatusBadge status={target.recommendation_status} type="recommendation" />
              <StatusBadge status={target.information_status} type="information" />
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setDrawerOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium border border-gray-200 text-gray-700 hover:border-brand-500 hover:text-brand-600 transition-colors"
          >
            <MessageSquarePlus className="w-3.5 h-3.5" />
            录入更新
          </button>
          <Link
            to={`/recommendations?mode=target-to-buyer&targetId=${target.id}`}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium bg-brand-600 text-white hover:bg-brand-700 transition-colors"
          >
            <Sparkles className="w-3.5 h-3.5" />
            推荐买家
          </Link>
        </div>
      </div>

      {/* Tabs + Content + Sidebar */}
      <div className="grid grid-cols-12 gap-5">
        {/* Main content */}
        <div className="col-span-8">
          <div className="bg-white border border-gray-200">
            <div className="flex items-center border-b border-gray-100 px-5">
              {tabs.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === tab.key
                      ? 'border-brand-600 text-brand-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <div className="p-5">
              {activeTab === 'info' && <InfoTab target={target} />}
              {activeTab === 'attachments' && <AttachmentsTab />}
              {activeTab === 'relations' && <RelationsTab />}
              {activeTab === 'history' && <HistoryTab logs={logs} />}
            </div>
          </div>
        </div>

        {/* Right sidebar */}
        <div className="col-span-4 space-y-4">
          <div className="bg-white border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <AlertCircle className="w-3.5 h-3.5 text-amber-500" />
              自动更新待复核
            </h3>
            <p className="text-xs text-gray-400">暂无待复核项</p>
          </div>
          <div className="bg-white border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">信息缺口</h3>
            <div className="space-y-1.5 text-xs text-gray-600">
              {!target.can_consolidate || target.can_consolidate === 'unknown' ? (
                <p>- 是否可并表</p>
              ) : null}
              {!target.can_control || target.can_control === 'unknown' ? (
                <p>- 是否可控股</p>
              ) : null}
              {!target.current_revenue_yuan ? <p>- 营收</p> : null}
              {!target.current_net_profit_yuan ? <p>- 利润</p> : null}
              {!target.valuation_yuan ? <p>- 估值</p> : null}
              {target.can_consolidate && target.can_consolidate !== 'unknown' &&
               target.can_control && target.can_control !== 'unknown' &&
               target.current_revenue_yuan && target.current_net_profit_yuan && target.valuation_yuan && (
                <p className="text-emerald-600">信息完善</p>
              )}
            </div>
          </div>
        </div>
      </div>

      <BusinessUpdateDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        defaultTargetId={target.id}
        defaultTargetName={target.target_name}
      />
    </div>
  );
}

function InfoTab({ target }: { target: SellerTarget }) {
  const groups = [
    {
      label: '身份',
      fields: [
        { label: '标的名称', value: target.target_name },
        { label: '类型', value: target.target_type || '公司整体' },
      ],
    },
    {
      label: '行业业务',
      fields: [
        { label: '一级行业', value: target.industry_primary },
        { label: '二级行业', value: target.industry_secondary },
        { label: '业务摘要', value: target.business_summary },
      ],
    },
    {
      label: '财务',
      fields: [
        { label: '营收', value: target.current_revenue_yuan ? formatYuan(target.current_revenue_yuan) : null },
        { label: '利润', value: target.current_net_profit_yuan ? formatYuan(target.current_net_profit_yuan) : null },
      ],
    },
    {
      label: '估值交易',
      fields: [
        { label: '估值', value: target.valuation_yuan ? formatYuan(target.valuation_yuan) : null },
        { label: '报价', value: target.asking_price_yuan ? formatYuan(target.asking_price_yuan) : null },
        { label: 'PE', value: target.pe_ratio ? Number(target.pe_ratio).toFixed(1) : null },
        { label: '是否还卖', value: target.is_for_sale },
        { label: '可控股', value: target.can_control },
        { label: '可并表', value: target.can_consolidate },
      ],
    },
    {
      label: '风险',
      fields: [
        { label: '风险摘要', value: target.risk_summary },
      ],
    },
  ];

  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <div key={group.label}>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">{group.label}</h4>
          <div className="grid grid-cols-2 gap-x-8 gap-y-2.5">
            {group.fields.map((field) => (
              <div key={field.label} className="flex items-baseline gap-2">
                <span className="text-xs text-gray-500 w-16 shrink-0">{field.label}</span>
                <span className="text-sm text-gray-800">{field.value || '-'}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function AttachmentsTab() {
  return (
    <div className="text-center py-10">
      <FileText className="w-8 h-8 text-gray-300 mx-auto mb-2" />
      <p className="text-sm text-gray-400">附件解析功能后端开发中</p>
    </div>
  );
}

function RelationsTab() {
  return (
    <div className="text-center py-10">
      <SearchIcon className="w-8 h-8 text-gray-300 mx-auto mb-2" />
      <p className="text-sm text-gray-400">关系与跟进记录后端开发中</p>
      <p className="text-xs text-gray-400 mt-1">推荐记录、买家接触将在此展示</p>
    </div>
  );
}

function HistoryTab({ logs }: { logs: UpdateLog[] }) {
  if (logs.length === 0) {
    return (
      <div className="text-center py-10">
        <Clock className="w-8 h-8 text-gray-300 mx-auto mb-2" />
        <p className="text-sm text-gray-400">暂无更新记录</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {logs.map((log) => (
        <div key={log.id} className="flex items-start gap-3 py-2 border-b border-gray-50 last:border-0">
          <span className="text-xs text-gray-400 font-mono w-32 shrink-0">
            {new Date(log.applied_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
          </span>
          <div className="min-w-0">
            <span className="text-sm text-gray-700">
              {log.field_path}: {log.old_value_json || '-'} → {log.new_value_json || '-'}
            </span>
            <span className="text-xs text-gray-400 ml-2">来源: {log.source_type}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function StatusBadge({ status, type }: { status: string; type: 'recommendation' | 'information' }) {
  const colors =
    type === 'recommendation'
      ? status === 'recommendable'
        ? 'bg-emerald-50 text-emerald-700'
        : 'bg-gray-100 text-gray-600'
      : status === 'normal'
        ? 'bg-emerald-50 text-emerald-700'
        : status === 'insufficient'
          ? 'bg-amber-50 text-amber-700'
          : 'bg-gray-100 text-gray-600';

  const label =
    type === 'recommendation'
      ? status === 'recommendable' ? '可推荐' : '暂不推荐'
      : status === 'normal' ? '信息完善' : status === 'insufficient' ? '信息不足' : status;

  return <span className={`text-xs px-1.5 py-0.5 font-medium ${colors}`}>{label}</span>;
}

function formatYuan(val: string): string {
  const num = Number(val);
  if (num >= 100000000) return `${(num / 100000000).toFixed(1)}亿`;
  if (num >= 10000) return `${(num / 10000).toFixed(0)}万`;
  return String(num);
}
