import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Sparkles,
  MessageSquarePlus,
  Search as SearchIcon,
  UserRound,
  AlertCircle,
  FileText,
  Clock,
} from 'lucide-react';
import { relations, sellerTargets, updateLogs } from '../lib/api';
import type { BuyerSellerRelation, RelationEvent, SellerTarget, UpdateLog } from '../types/api';
import BusinessUpdateDrawer from '../components/BusinessUpdateDrawer';

type Tab = 'info' | 'attachments' | 'relations' | 'history';

export default function TargetDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [target, setTarget] = useState<SellerTarget | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>('info');
  const [logs, setLogs] = useState<UpdateLog[]>([]);
  const [relationItems, setRelationItems] = useState<BuyerSellerRelation[]>([]);
  const [relationEvents, setRelationEvents] = useState<RelationEvent[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    sellerTargets.get(id)
      .then(setTarget)
      .catch(() => navigate('/targets'))
      .finally(() => setLoading(false));
    Promise.all([
      updateLogs.list({ entity_type: 'seller_target', entity_id: id }),
      relations.list({ seller_target_id: id, limit: 50 }),
      relations.listEvents({ seller_target_id: id, limit: 50 }),
    ])
      .then(([nextLogs, nextRelations, nextEvents]) => {
        setLogs(nextLogs);
        setRelationItems(nextRelations);
        setRelationEvents(nextEvents);
      })
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
              {target.asking_price_yuan && <span>· 报价{formatYuan(target.asking_price_yuan)}*</span>}
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
              {activeTab === 'relations' && (
                <RelationsTab relationItems={relationItems} relationEvents={relationEvents} />
              )}
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
        { label: '标的主体', value: getSubjectDisplay(target) },
        { label: '类型', value: target.target_type || '公司整体' },
        { label: '上市状态', value: formatListedStatus(target.listed_status) },
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
        { label: '估值时间', value: target.valuation_date },
        { label: '报价', value: target.asking_price_yuan ? formatYuan(target.asking_price_yuan) : null },
        { label: '报价时间', value: target.asking_price_date },
        { label: 'PE', value: target.pe_ratio ? Number(target.pe_ratio).toFixed(1) : null },
        { label: '出售比例', value: target.transfer_ratio_text || formatTransferRatio(target) },
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

function RelationsTab({
  relationItems,
  relationEvents,
}: {
  relationItems: BuyerSellerRelation[];
  relationEvents: RelationEvent[];
}) {
  if (relationItems.length === 0 && relationEvents.length === 0) {
    return (
      <div className="text-center py-10">
        <SearchIcon className="w-8 h-8 text-gray-300 mx-auto mb-2" />
        <p className="text-sm text-gray-400">暂无关系与跟进记录</p>
        <p className="text-xs text-gray-400 mt-1">推荐、接触、尽调和不感兴趣等进展会自动沉淀在这里</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {relationItems.length > 0 && (
        <section>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">当前关系</h4>
          <div className="space-y-2">
            {relationItems.map((relation) => (
              <div key={relation.id} className="border border-gray-100 px-3 py-2.5">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 flex items-center gap-1.5">
                      <UserRound className="w-3.5 h-3.5 text-gray-400" />
                      {relation.buyer_name || '未绑定买家'} / {relation.buyer_intent_name || '未命名意向'}
                    </p>
                    {relation.last_event_summary && (
                      <p className="text-xs text-gray-500 mt-1 line-clamp-2">{relation.last_event_summary}</p>
                    )}
                  </div>
                  <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-700 shrink-0">
                    {relationStatusLabel(relation.status)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {relationEvents.length > 0 && (
        <section>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">跟进时间线</h4>
          <div className="space-y-2">
            {relationEvents.map((event) => (
              <div key={event.id} className="flex items-start gap-3 py-2 border-b border-gray-50 last:border-0">
                <span className="text-xs text-gray-400 font-mono w-32 shrink-0">
                  {new Date(event.event_time).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                </span>
                <div className="min-w-0">
                  <p className="text-sm text-gray-800">
                    {event.buyer_name || '未绑定买家'} / {event.buyer_intent_name || '未命名意向'}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {eventTypeLabel(event.event_type)}{event.title ? ` · ${event.title}` : ''}
                  </p>
                  {event.content && <p className="text-xs text-gray-600 mt-1">{event.content}</p>}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function relationStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    recommended: '已推荐',
    interested: '感兴趣',
    in_discussion: '沟通中',
    due_diligence: '尽调中',
    agreement: '协议阶段',
    deal_closed: '已成交',
    not_interested: '不感兴趣',
    paused: '暂停',
    lost: '失败',
  };
  return labels[status] || status;
}

function eventTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    recommended: '推荐',
    buyer_interested: '买家感兴趣',
    buyer_not_interested: '买家不感兴趣',
    meeting: '会议',
    call: '电话',
    material_sent: '发送资料',
    due_diligence_started: '启动尽调',
    agreement_discussion: '协议沟通',
    deal_closed: '成交',
    paused: '暂停',
    internal_note: '内部备注',
    other: '其他',
  };
  return labels[type] || type;
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
  if (!Number.isFinite(num)) return '-';
  const sign = num < 0 ? '-' : '';
  const abs = Math.abs(num);
  if (abs >= 100000000) return `${sign}${(abs / 100000000).toFixed(1)}亿`;
  if (abs >= 10000) return `${sign}${Math.round(abs / 10000)}万`;
  return String(num);
}

function formatListedStatus(status: string | null): string {
  if (status === 'listed') return '已上市';
  if (status === 'unlisted' || status === 'pre_ipo') return '未上市';
  return '未知';
}

function getSubjectDisplay(target: SellerTarget): string {
  const subject = target.target_subject_name?.trim();
  if (target.target_type === 'company' && (!subject || subject === target.target_name)) return '同标的';
  return subject || '-';
}

function formatTransferRatio(target: SellerTarget): string | null {
  if (target.transfer_ratio_min && target.transfer_ratio_max) {
    return `${formatRatio(target.transfer_ratio_min)}-${formatRatio(target.transfer_ratio_max)}`;
  }
  if (target.transfer_ratio_min) return `>=${formatRatio(target.transfer_ratio_min)}`;
  if (target.transfer_ratio_max) return `<=${formatRatio(target.transfer_ratio_max)}`;
  return null;
}

function formatRatio(value: string): string {
  const num = Number(value);
  if (!Number.isFinite(num)) return value;
  return `${Number(num.toFixed(1))}%`;
}
