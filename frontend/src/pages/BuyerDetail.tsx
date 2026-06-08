import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft,
  Sparkles,
  MessageSquarePlus,
  Clock,
  Search as SearchIcon,
  X,
  Building2,
  MapPin,
  TrendingUp,
  Star,
  CheckCircle2,
  Ban,
} from 'lucide-react';
import { buyerParties, relations, updateLogs } from '../lib/api';
import type { BuyerParty, BuyerIntent, BuyerSellerRelation, RelationEvent, UpdateLog } from '../types/api';
import BusinessUpdateDrawer from '../components/BusinessUpdateDrawer';

type Tab = 'info' | 'intents' | 'relations' | 'history';

export default function BuyerDetail() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [party, setParty] = useState<BuyerParty | null>(null);
  const [intents, setIntents] = useState<BuyerIntent[]>([]);
  const [logs, setLogs] = useState<UpdateLog[]>([]);
  const [relationItems, setRelationItems] = useState<BuyerSellerRelation[]>([]);
  const [relationEvents, setRelationEvents] = useState<RelationEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>('intents');
  const [selectedIntentId, setSelectedIntentId] = useState<string | null>(
    searchParams.get('intentId')
  );
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    Promise.all([
      buyerParties.get(id),
      buyerParties.intents(id),
      updateLogs.list({ entity_type: 'buyer_party', entity_id: id }),
      relations.list({ buyer_party_id: id, limit: 50 }),
      relations.listEvents({ buyer_party_id: id, limit: 50 }),
    ])
      .then(([p, i, l, nextRelations, nextEvents]) => {
        setParty(p);
        setIntents(i);
        setLogs(l);
        setRelationItems(nextRelations);
        setRelationEvents(nextEvents);
      })
      .catch(() => navigate('/buyers'))
      .finally(() => setLoading(false));
  }, [id, navigate]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!party) return null;

  const tabs: { key: Tab; label: string }[] = [
    { key: 'info', label: '基本信息' },
    { key: 'intents', label: '意向' },
    { key: 'relations', label: '关系/跟进' },
    { key: 'history', label: '更新记录' },
  ];

  const selectedIntent = intents.find((i) => i.id === selectedIntentId);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/buyers" className="p-1.5 text-gray-400 hover:text-gray-600">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-lg font-semibold text-gray-900">{party.buyer_name}</h1>
            <p className="text-xs text-gray-500 mt-0.5 flex items-center gap-2">
              {party.buyer_type && <span>{party.buyer_type}</span>}
              {party.region_province && <span>· {party.region_province}{party.region_city || ''}</span>}
              {party.main_business && <span>· {party.main_business}</span>}
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
        </div>
      </div>

      {/* Main area */}
      <div className="grid grid-cols-12 gap-5">
        <div className={selectedIntent ? 'col-span-7' : 'col-span-12'}>
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
              {activeTab === 'info' && <BuyerInfoTab party={party} />}
              {activeTab === 'intents' && (
                <IntentsTab
                  intents={intents}
                  selectedId={selectedIntentId}
                  onSelect={setSelectedIntentId}
                />
              )}
              {activeTab === 'relations' && (
                <RelationsTab
                  relationItems={relationItems}
                  relationEvents={relationEvents}
                  selectedIntentId={selectedIntentId}
                />
              )}
              {activeTab === 'history' && <HistoryTab logs={logs} />}
            </div>
          </div>
        </div>

        {/* Intent Drawer (inline right panel) */}
        {selectedIntent && (
          <div className="col-span-5">
            <IntentPanel
              intent={selectedIntent}
              onClose={() => setSelectedIntentId(null)}
            />
          </div>
        )}
      </div>

      <BusinessUpdateDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        defaultBuyerPartyId={party.id}
        defaultBuyerPartyName={party.buyer_name}
        defaultIntentId={selectedIntent?.id}
        defaultIntentName={selectedIntent?.intent_name}
      />
    </div>
  );
}

function BuyerInfoTab({ party }: { party: BuyerParty }) {
  return (
    <div className="space-y-5">
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">基本信息</h4>
        <div className="grid grid-cols-2 gap-x-8 gap-y-2.5">
          <Field label="买家名称" value={party.buyer_name} />
          <Field label="法人全称" value={party.legal_name} />
          <Field label="类型" value={party.buyer_type} />
          <Field label="集团" value={party.group_name} />
          <Field label="地区" value={`${party.region_province || ''} ${party.region_city || ''}`} />
          <Field label="上市状态" value={party.listed_status} />
        </div>
      </div>
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">画像</h4>
        <div className="space-y-2">
          <Field label="主营业务" value={party.main_business} />
          <Field label="资金实力" value={party.capital_strength_summary} />
          <Field label="画像摘要" value={party.profile_summary} />
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-xs text-gray-500 w-16 shrink-0">{label}</span>
      <span className="text-sm text-gray-800">{value || '-'}</span>
    </div>
  );
}

function IntentsTab({
  intents,
  selectedId,
  onSelect,
}: {
  intents: BuyerIntent[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  if (intents.length === 0) {
    return <p className="text-sm text-gray-400 py-6 text-center">暂无买家意向</p>;
  }

  return (
    <div className="space-y-2">
      {intents.map((intent) => (
        <div
          key={intent.id}
          onClick={() => onSelect(intent.id === selectedId ? null : intent.id)}
          className={`border p-3 cursor-pointer transition-all ${
            intent.id === selectedId
              ? 'border-brand-500 bg-brand-50'
              : 'border-gray-200 hover:border-brand-300'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-gray-900">{intent.intent_name}</span>
            <span className={`text-xs px-1.5 py-0.5 font-medium ${
              intent.status === 'active'
                ? 'bg-emerald-50 text-emerald-700'
                : 'bg-gray-100 text-gray-600'
            }`}>
              {intent.status === 'active' ? '继续推荐' : '暂停推荐'}
            </span>
          </div>
          <div className="flex items-center gap-3 mt-1.5 text-xs text-gray-500">
            {intent.industry_primary && <span>{intent.industry_primary}</span>}
            {intent.region_scope_summary && <span>· {intent.region_scope_summary}</span>}
            {intent.min_net_profit_yuan && <span>· 利润{'>='}{(Number(intent.min_net_profit_yuan) / 10000).toFixed(0)}万</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

function IntentPanel({ intent, onClose }: { intent: BuyerIntent; onClose: () => void }) {
  return (
    <div className="bg-white border border-gray-200 h-full">
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-900">{intent.intent_name}</h3>
        <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600">
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="p-5 space-y-5 overflow-y-auto max-h-[60vh]">
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">状态：</span>
          <span className={`text-xs px-1.5 py-0.5 font-medium ${
            intent.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600'
          }`}>
            {intent.status === 'active' ? '继续推荐' : '暂停推荐'}
          </span>
        </div>
        {intent.contact_name && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-gray-500">联系人：</span>
            <span className="text-gray-800">{intent.contact_name}</span>
          </div>
        )}

        <div>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Hard 条件</h4>
          <div className="space-y-2">
            {intent.industry_primary && <CondRow icon={Building2} label="行业" value={intent.industry_primary} />}
            {intent.region_scope_summary && <CondRow icon={MapPin} label="区域" value={intent.region_scope_summary} />}
            {intent.min_net_profit_yuan && <CondRow icon={TrendingUp} label="利润" value={`>=${(Number(intent.min_net_profit_yuan) / 10000).toFixed(0)}万`} />}
            {intent.max_pe && <CondRow icon={Star} label="PE" value={`<=${Number(intent.max_pe).toFixed(0)}`} />}
            {marketCapRangeLabel(intent) !== '-' && <CondRow icon={TrendingUp} label="市值" value={marketCapRangeLabel(intent)} />}
            {listingRequirementLabel(intent) !== '-' && <CondRow icon={Star} label="上市" value={listingRequirementLabel(intent)} />}
            {intent.max_debt_ratio && <CondRow icon={TrendingUp} label="负债" value={`<=${Number(intent.max_debt_ratio).toFixed(0)}%`} />}
            {intent.requires_consolidation && intent.requires_consolidation !== 'unknown' && (
              <CondRow icon={CheckCircle2} label="并表" value={intent.requires_consolidation === 'yes' ? '需要' : '不需要'} />
            )}
          </div>
        </div>

        {(intent.preference_summary || intent.premium_tolerance_summary || intent.buyer_industry_advantage_summary) && (
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Preference</h4>
            <div className="space-y-1.5 text-sm text-gray-600">
              {intent.preference_summary && <p>{intent.preference_summary}</p>}
              {intent.premium_tolerance_summary && <p>溢价：{intent.premium_tolerance_summary}</p>}
              {intent.buyer_industry_advantage_summary && <p>收购方优势：{intent.buyer_industry_advantage_summary}</p>}
            </div>
          </div>
        )}

        {intent.negative_summary && (
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">排除项</h4>
            <div className="flex items-center gap-2 text-sm text-gray-600">
              <Ban className="w-3.5 h-3.5 text-gray-400" />
              {intent.negative_summary}
            </div>
            {intent.major_risk_tolerance_summary && (
              <p className="mt-1.5 text-sm text-gray-600">风险容忍：{intent.major_risk_tolerance_summary}</p>
            )}
          </div>
        )}

        {intent.unknown_summary && (
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Unknown / 待确认</h4>
            <p className="text-sm text-gray-600">{intent.unknown_summary}</p>
          </div>
        )}

        <div className="flex items-center gap-2 pt-3 border-t border-gray-100">
          <Link
            to={`/recommendations?mode=buyer-to-target&intentId=${intent.id}`}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-brand-600 text-white hover:bg-brand-700 transition-colors"
          >
            <Sparkles className="w-3 h-3" />
            推荐标的
          </Link>
          <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-gray-200 text-gray-700 hover:border-brand-500 hover:text-brand-600 transition-colors">
            <MessageSquarePlus className="w-3 h-3" />
            录入更新
          </button>
        </div>
      </div>
    </div>
  );
}

function listingRequirementLabel(intent: BuyerIntent): string {
  const status: Record<string, string> = {
    listed: '已上市',
    preparing_listing: '准备上市',
    pre_ipo: 'pre-IPO',
    unlisted: '未上市',
    any: '均可',
    unknown: '未知',
  };
  const parts = [
    intent.preferred_listed_status ? status[intent.preferred_listed_status] || intent.preferred_listed_status : null,
    intent.listing_board_requirement_summary,
    intent.financing_stage_requirement_summary,
  ].filter(Boolean);
  return parts.length ? parts.join(' / ') : '-';
}

function marketCapRangeLabel(intent: BuyerIntent): string {
  if (intent.market_cap_range_summary) return intent.market_cap_range_summary;
  const min = intent.min_market_cap_yuan ? `${(Number(intent.min_market_cap_yuan) / 100000000).toFixed(1)}亿` : '';
  const max = intent.max_market_cap_yuan ? `${(Number(intent.max_market_cap_yuan) / 100000000).toFixed(1)}亿` : '';
  if (min && max) return `${min}-${max}`;
  if (min) return `≥${min}`;
  if (max) return `≤${max}`;
  return '-';
}

function CondRow({ icon: Icon, label, value }: { icon: typeof Building2; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <Icon className="w-3.5 h-3.5 text-gray-400 shrink-0" />
      <span className="text-gray-500 w-10 shrink-0">{label}</span>
      <span className="text-gray-800">{value}</span>
    </div>
  );
}

function RelationsTab({
  relationItems,
  relationEvents,
  selectedIntentId,
}: {
  relationItems: BuyerSellerRelation[];
  relationEvents: RelationEvent[];
  selectedIntentId: string | null;
}) {
  const filteredRelations = selectedIntentId
    ? relationItems.filter((relation) => relation.buyer_intent_id === selectedIntentId)
    : relationItems;
  const filteredEvents = selectedIntentId
    ? relationEvents.filter((event) => event.buyer_intent_id === selectedIntentId)
    : relationEvents;

  if (filteredRelations.length === 0 && filteredEvents.length === 0) {
    return (
      <div className="text-center py-10">
        <SearchIcon className="w-8 h-8 text-gray-300 mx-auto mb-2" />
        <p className="text-sm text-gray-400">暂无关系与跟进记录</p>
        <p className="text-xs text-gray-400 mt-1">被推荐的标的和后续沟通会自动沉淀在这里</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {filteredRelations.length > 0 && (
        <section>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">当前关系</h4>
          <div className="space-y-2">
            {filteredRelations.map((relation) => (
              <div key={relation.id} className="border border-gray-100 px-3 py-2.5">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900">{relation.seller_target_name || '未命名标的'}</p>
                    <p className="text-xs text-gray-500 mt-0.5">{relation.buyer_intent_name || '未命名意向'}</p>
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

      {filteredEvents.length > 0 && (
        <section>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">跟进时间线</h4>
          <div className="space-y-2">
            {filteredEvents.map((event) => (
              <div key={event.id} className="flex items-start gap-3 py-2 border-b border-gray-50 last:border-0">
                <span className="text-xs text-gray-400 font-mono w-32 shrink-0">
                  {new Date(event.event_time).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                </span>
                <div className="min-w-0">
                  <p className="text-sm text-gray-800">{event.seller_target_name || '未命名标的'}</p>
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
          <span className="text-sm text-gray-700">
            {log.field_path}: {log.old_value_json || '-'} → {log.new_value_json || '-'}
          </span>
        </div>
      ))}
    </div>
  );
}
