import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  Clock,
  Loader2,
  MessageSquarePlus,
  Sparkles,
} from 'lucide-react';
import { buyerIntents, buyerParties, relations } from '../lib/api';
import type {
  BuyerIntent,
  BuyerIntentParseStatus,
  BuyerParty,
  BuyerSellerRelation,
  RelationEvent,
} from '../types/api';
import BusinessUpdateDrawer from '../components/BusinessUpdateDrawer';
import UpdateHistory from '../components/UpdateHistory';
import { valueLabel } from '../lib/fieldLabels';

export default function BuyerIntentDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [intent, setIntent] = useState<BuyerIntent | null>(null);
  const [party, setParty] = useState<BuyerParty | null>(null);
  const [parseStatus, setParseStatus] = useState<BuyerIntentParseStatus | null>(null);
  const [relationItems, setRelationItems] = useState<BuyerSellerRelation[]>([]);
  const [relationEvents, setRelationEvents] = useState<RelationEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusSaving, setStatusSaving] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    buyerIntents
      .get(id)
      .then(async (nextIntent) => {
        setIntent(nextIntent);
        const [nextParseStatus, nextRelations, nextEvents, nextParty] = await Promise.all([
          buyerIntents.parseStatus(id).catch(() => null),
          relations.list({ buyer_intent_id: id, limit: 50 }).catch(() => []),
          relations.listEvents({ buyer_intent_id: id, limit: 50 }).catch(() => []),
          nextIntent.buyer_party_id ? buyerParties.get(nextIntent.buyer_party_id).catch(() => null) : Promise.resolve(null),
        ]);
        setParseStatus(nextParseStatus);
        setRelationItems(nextRelations);
        setRelationEvents(nextEvents);
        setParty(nextParty);
      })
      .catch(() => navigate('/buyers'))
      .finally(() => setLoading(false));
  }, [id, navigate]);

  const updateStatus = async (value: string) => {
    if (!intent || value === intent.status) return;
    setStatusSaving(true);
    try {
      const updated = await buyerIntents.update(intent.id, { status: value });
      setIntent(updated);
    } catch (err) {
      alert(err instanceof Error ? err.message : '更新状态失败');
    } finally {
      setStatusSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!intent) return null;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <Link to="/buyers" className="p-1.5 text-gray-400 hover:text-gray-600">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-gray-900 truncate">{intent.intent_name}</h1>
            <p className="text-xs text-gray-500 mt-0.5 flex items-center gap-2">
              {party ? (
                <Link to={`/buyers/${party.id}`} className="hover:text-brand-600">{party.buyer_name}</Link>
              ) : (
                <span>{intent.buyer_name || '未关联买家'}</span>
              )}
              <span>· 负责人：{intent.owner_name || '未指派'}</span>
              <span>· 更新于 {shortDateTime(intent.updated_at)}</span>
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={intent.status}
            onChange={(event) => updateStatus(event.target.value)}
            disabled={statusSaving}
            className="px-2 py-1.5 text-sm border border-gray-200 text-gray-700 bg-white outline-none hover:border-brand-500 focus:border-brand-600 disabled:opacity-50"
          >
            <option value="active">持续推荐</option>
            <option value="paused">暂停推荐</option>
            <option value="closed">已结束</option>
          </select>
          <Link
            to={`/recommendations?mode=buyer-to-target&intentId=${intent.id}`}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium bg-brand-600 text-white hover:bg-brand-700 transition-colors"
          >
            <Sparkles className="w-3.5 h-3.5" />
            推荐标的
          </Link>
          <button
            onClick={() => setDrawerOpen(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium border border-gray-200 text-gray-700 hover:border-brand-500 hover:text-brand-600 transition-colors"
          >
            <MessageSquarePlus className="w-3.5 h-3.5" />
            录入更新
          </button>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-5">
        <div className="col-span-8 space-y-5">
          <Section title="需求字段">
            <div className="grid grid-cols-2 gap-x-8 gap-y-3">
              <Info label="行业" value={[intent.industry_primary, intent.industry_secondary].filter(Boolean).join(' / ')} />
              <Info label="地区" value={intent.region_scope_summary} />
              <Info label="上市要求" value={listingRequirementLabel(intent)} />
              <Info label="市值范围" value={marketCapRangeLabel(intent)} />
              <Info label="最低营收" value={moneyText(intent.min_revenue_yuan)} />
              <Info label="最低净利润" value={moneyText(intent.min_net_profit_yuan)} />
              <Info label="PE 上限" value={numberText(intent.max_pe)} />
              <Info label="估值上限" value={moneyText(intent.max_valuation_yuan)} />
              <Info label="控股要求" value={valueLabel('yes_no_like', intent.requires_control)} />
              <Info label="并表要求" value={valueLabel('yes_no_like', intent.requires_consolidation)} />
              <Info label="股权比例" value={intent.equity_ratio_summary} />
              <Info label="交易方式" value={transactionText(intent)} />
              <Info label="溢价要求" value={intent.premium_tolerance_summary || percentText(intent.max_premium_rate)} />
              <Info label="负债率要求" value={intent.debt_ratio_requirement_summary || percentText(intent.max_debt_ratio)} />
            </div>
          </Section>

          <Section title="偏好与排除">
            <div className="space-y-3">
              <Info label="需求摘要" value={intent.intent_summary} wide />
              <Info label="优先级" value={intent.priority_summary} wide />
              <Info label="偏好" value={intent.preference_summary} wide />
              <Info label="收购方优势" value={intent.buyer_industry_advantage_summary} wide />
              <Info label="风险容忍" value={intent.major_risk_tolerance_summary} wide />
              <Info label="排除项" value={intent.negative_summary} wide />
              <Info label="待确认" value={intent.unknown_summary} wide />
            </div>
          </Section>

          <Section title="原始材料">
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
              {intent.raw_requirement_text || '暂无原始材料'}
            </p>
          </Section>

          <Section title="推荐与跟进">
            <RelationsList relations={relationItems} events={relationEvents} />
          </Section>
        </div>

        <div className="col-span-4 space-y-5">
          <Section title="解析状态">
            <ParseStatusCard intent={intent} parseStatus={parseStatus} />
          </Section>

          <Section title="买家主体">
            <div className="space-y-2">
              <Info label="买家" value={party?.buyer_name || intent.buyer_name} wide />
              <Info label="类型" value={party?.buyer_type ? valueLabel('buyer_type', party.buyer_type) : null} wide />
              <Info label="地区" value={party ? `${party.region_province || ''} ${party.region_city || ''}`.trim() : null} wide />
              <Info label="主营业务" value={party?.main_business} wide />
              <Info label="资金实力" value={party?.capital_strength_summary} wide />
              <Info label="备注" value={party?.notes} wide />
            </div>
          </Section>

        </div>
      </div>

      <Section title="更新记录">
        <UpdateHistory
          entityType="buyer_intent"
          entityId={intent.id}
          refreshKey={historyRefreshKey}
          onProcessingSettled={async () => {
            const [fresh, freshParseStatus] = await Promise.all([
              buyerIntents.get(intent.id),
              buyerIntents.parseStatus(intent.id).catch(() => null),
            ]);
            setIntent(fresh);
            setParseStatus(freshParseStatus);
          }}
          onRolledBack={async () => {
            const fresh = await buyerIntents.get(intent.id);
            setIntent(fresh);
            setParseStatus(await buyerIntents.parseStatus(intent.id).catch(() => null));
          }}
        />
      </Section>

      <BusinessUpdateDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        defaultBuyerPartyId={intent.buyer_party_id || undefined}
        defaultBuyerPartyName={intent.buyer_name || party?.buyer_name}
        defaultIntentId={intent.id}
        defaultIntentName={intent.intent_name}
        onSuccess={() => {
          buyerIntents.get(intent.id).then(setIntent).catch(() => {});
          setHistoryRefreshKey((value) => value + 1);
        }}
      />
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="bg-white border border-gray-200">
      <div className="px-5 py-3 border-b border-gray-100">
        <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function Info({ label, value, wide }: { label: string; value: string | number | null | undefined; wide?: boolean }) {
  return (
    <div className={wide ? 'flex items-start gap-2' : 'flex items-baseline gap-2'}>
      <span className="text-xs text-gray-500 w-20 shrink-0">{label}</span>
      <span className="text-sm text-gray-800 whitespace-pre-wrap">{value || '-'}</span>
    </div>
  );
}

function ParseStatusCard({ intent, parseStatus }: { intent: BuyerIntent; parseStatus: BuyerIntentParseStatus | null }) {
  const job = parseStatus?.latest_job;
  const active = job?.status === 'queued' || job?.status === 'running' || job?.status === 'retry_waiting';
  const label = job ? parseJobLabel(job.status) : hasStructuredIntentFields(intent) ? '已解析' : '未解析';
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {active ? <Loader2 className="w-4 h-4 animate-spin text-brand-600" /> : <Clock className="w-4 h-4 text-gray-400" />}
        <span className="text-sm font-medium text-gray-900">{label}</span>
      </div>
      {job?.error_message && <p className="text-xs text-red-600">{job.error_message}</p>}
      {job && (
        <p className="text-xs text-gray-500">
          尝试 {job.attempt_count}/{job.max_attempts} · {job.finished_at ? `完成于 ${shortDateTime(job.finished_at)}` : `创建于 ${shortDateTime(job.created_at)}`}
        </p>
      )}
    </div>
  );
}

function RelationsList({ relations: relationItems, events }: { relations: BuyerSellerRelation[]; events: RelationEvent[] }) {
  if (relationItems.length === 0 && events.length === 0) {
    return <p className="text-sm text-gray-400 py-4">暂无推荐和跟进记录</p>;
  }
  return (
    <div className="space-y-4">
      {relationItems.map((relation) => (
        <div key={relation.id} className="border border-gray-100 px-3 py-2.5">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm font-medium text-gray-900">{relation.seller_target_name || '未命名标的'}</p>
              {relation.last_event_summary && <p className="text-xs text-gray-500 mt-1 line-clamp-2">{relation.last_event_summary}</p>}
            </div>
            <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-700 shrink-0">{relation.status}</span>
          </div>
        </div>
      ))}
      {events.slice(0, 8).map((event) => (
        <div key={event.id} className="flex items-start gap-3 border-t border-gray-50 pt-3">
          <Clock className="w-3.5 h-3.5 text-gray-300 mt-0.5 shrink-0" />
          <div className="min-w-0">
            <p className="text-xs text-gray-500">{shortDateTime(event.event_time)} · {event.event_type}</p>
            {event.title && <p className="text-sm text-gray-800 mt-0.5">{event.title}</p>}
            {event.content && <p className="text-xs text-gray-600 mt-1 line-clamp-2">{event.content}</p>}
          </div>
        </div>
      ))}
    </div>
  );
}

function listingRequirementLabel(intent: BuyerIntent): string {
  const parts = [
    intent.preferred_listed_status ? valueLabel('preferred_listed_status', intent.preferred_listed_status) : null,
    intent.listing_board_requirement_summary,
    intent.financing_stage_requirement_summary,
  ].filter(Boolean);
  return parts.length ? parts.join(' / ') : '-';
}

function marketCapRangeLabel(intent: BuyerIntent): string {
  if (intent.market_cap_range_summary) return intent.market_cap_range_summary;
  const min = intent.min_market_cap_yuan ? formatCompactMoney(Number(intent.min_market_cap_yuan)) : '';
  const max = intent.max_market_cap_yuan ? formatCompactMoney(Number(intent.max_market_cap_yuan)) : '';
  if (min && max) return `${min}-${max}`;
  if (min) return `≥${min}`;
  if (max) return `≤${max}`;
  return '-';
}

function transactionText(intent: BuyerIntent): string | null {
  if (intent.transaction_type) return intent.transaction_type;
  if (Array.isArray(intent.transaction_types_json)) return intent.transaction_types_json.join('、');
  return null;
}

function hasStructuredIntentFields(intent: BuyerIntent): boolean {
  return Boolean(intent.intent_summary || intent.industry_primary || intent.region_scope_summary || intent.min_net_profit_yuan);
}

function moneyText(value: string | number | null | undefined): string | null {
  if (value === null || value === undefined || value === '') return null;
  return formatCompactMoney(Number(value));
}

function numberText(value: string | number | null | undefined): string | null {
  if (value === null || value === undefined || value === '') return null;
  return Number(value).toFixed(0);
}

function percentText(value: string | number | null | undefined): string | null {
  if (value === null || value === undefined || value === '') return null;
  return `${Number(value).toFixed(0)}%`;
}

function formatCompactMoney(value: number): string {
  if (!Number.isFinite(value)) return '-';
  if (Math.abs(value) < 10000) return `${value.toFixed(0)}元`;
  if (Math.abs(value) < 100000000) return `${(value / 10000).toFixed(0)}万`;
  return `${(value / 100000000).toFixed(1)}亿`;
}

function shortDateTime(value: string | null | undefined): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function parseJobLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    running: '解析中',
    retry_waiting: '等待重试',
    succeeded: '已解析',
    failed: '解析失败',
    cancelled: '已取消',
  };
  return labels[status] || status;
}
