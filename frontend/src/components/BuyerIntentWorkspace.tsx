import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import {
  AlertCircle,
  Download,
  FileText,
  Loader2,
  RefreshCw,
  Search,
} from 'lucide-react';
import { attachments, buyerIntents, buyerParties } from '../lib/api';
import type {
  AttachmentItem,
  BuyerIntent,
  BuyerIntentFollowUp,
  BuyerIntentParseStatus,
  BuyerParty,
  BuyerPartyCreate,
} from '../types/api';
import { valueLabel } from '../lib/fieldLabels';
import UpdateHistory from './UpdateHistory';
import ProgressPanel from '../features/relations/ProgressPanel';

export type BuyerWorkspaceTab = 'intent' | 'buyer' | 'progress' | 'attachments' | 'followups' | 'history';

interface Props {
  intent: BuyerIntent;
  party: BuyerParty | null;
  parseStatus: BuyerIntentParseStatus | null;
  followUps: BuyerIntentFollowUp[];
  activeTab: BuyerWorkspaceTab;
  onTabChange: (tab: BuyerWorkspaceTab) => void;
  historyRefreshKey?: number;
  onPartySaved?: (party: BuyerParty) => void;
  onIntentRefresh?: () => void | Promise<void>;
}

const TABS: Array<{ key: BuyerWorkspaceTab; label: string }> = [
  { key: 'intent', label: '需求信息' },
  { key: 'buyer', label: '买家资料' },
  { key: 'progress', label: '推进' },
  { key: 'attachments', label: '附件与证据' },
  { key: 'followups', label: '跟进记录' },
  { key: 'history', label: '更新记录' },
];

export default function BuyerIntentWorkspace({
  intent,
  party,
  parseStatus,
  followUps,
  activeTab,
  onTabChange,
  historyRefreshKey = 0,
  onPartySaved,
  onIntentRefresh,
}: Props) {
  return (
    <div className="border border-gray-200 bg-white">
      <div className="flex overflow-x-auto border-b border-gray-100 px-5">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => onTabChange(tab.key)}
            className={`shrink-0 border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
              activeTab === tab.key
                ? 'border-brand-600 text-brand-600'
                : 'border-transparent text-gray-500 hover:text-gray-800'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className={activeTab === 'history' ? '' : 'p-5'}>
        {activeTab === 'intent' ? <IntentOverview intent={intent} parseStatus={parseStatus} /> : null}
        {activeTab === 'buyer' ? (
          party ? (
            <BuyerInfo party={party} onSaved={onPartySaved} />
          ) : (
            <EmptyState title="当前需求未关联买家" description="可在买家管理中补充关联关系。" />
          )
        ) : null}
        {activeTab === 'progress' ? <ProgressPanel side="buyer_intent" entityId={intent.id} /> : null}
        {activeTab === 'attachments' ? <IntentAttachments intentId={intent.id} /> : null}
        {activeTab === 'followups' ? <IntentFollowUps intentId={intent.id} items={followUps} onRefresh={onIntentRefresh} /> : null}
        {activeTab === 'history' ? (
          <UpdateHistory
            entityType="buyer_intent"
            entityId={intent.id}
            refreshKey={historyRefreshKey}
            onRolledBack={onIntentRefresh}
            onProcessingSettled={onIntentRefresh}
          />
        ) : null}
      </div>
    </div>
  );
}

export function IntentParseBadge({
  intent,
  parseStatus,
}: {
  intent: BuyerIntent;
  parseStatus: BuyerIntentParseStatus | null;
}) {
  const status = parseStatus?.latest_job?.status;
  const active = status === 'queued' || status === 'running' || status === 'retry_waiting';
  const failed = status === 'failed';
  const label = active ? '解析中' : failed ? '解析失败' : hasStructuredIntentFields(intent) ? '已解析' : '未解析';
  const className = active
    ? 'bg-blue-50 text-blue-700'
    : failed
      ? 'bg-red-50 text-red-700'
      : label === '已解析'
        ? 'bg-emerald-50 text-emerald-700'
        : 'bg-gray-100 text-gray-600';
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium ${className}`}>
      {active ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
      {label}
    </span>
  );
}

export function IntentStatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    active: '持续推荐',
    paused: '暂停推荐',
    closed: '已结束',
  };
  const className = status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600';
  return <span className={`px-2 py-0.5 text-xs font-medium ${className}`}>{labels[status] || status}</span>;
}

function IntentOverview({ intent, parseStatus }: { intent: BuyerIntent; parseStatus: BuyerIntentParseStatus | null }) {
  const latestJob = parseStatus?.latest_job;
  return (
    <div className="space-y-7">
      {latestJob?.status === 'failed' ? (
        <div className="flex items-start gap-2 border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium">最近一次解析失败</p>
            <p className="mt-1 text-xs leading-5">{latestJob.error_message || '请重新录入更新，或联系管理员在任务中心处理。'}</p>
          </div>
        </div>
      ) : null}

      <SectionTitle>核心条件</SectionTitle>
      <div className="grid grid-cols-1 gap-x-10 gap-y-3 md:grid-cols-2">
        <Info label="所属行业" value={[intent.industry_primary, intent.industry_secondary].filter(Boolean).join(' / ')} />
        <Info label="地域范围" value={intent.region_scope_summary} />
        <Info label="上市要求" value={listingRequirementLabel(intent)} />
        <Info label="市值范围" value={marketCapRangeLabel(intent)} />
        <Info label="最低营收" value={moneyText(intent.min_revenue_yuan)} />
        <Info label="最低净利润" value={moneyText(intent.min_net_profit_yuan)} />
        <Info label="PE 上限" value={numberText(intent.max_pe)} />
        <Info label="PS 上限" value={numberText(intent.max_ps)} />
        <Info label="最低净利率" value={percentText(intent.min_net_margin)} />
        <Info label="最低毛利率" value={percentText(intent.min_gross_margin)} />
        <Info label="估值范围" value={valuationRangeLabel(intent)} />
        <Info label="估值上限" value={moneyText(intent.max_valuation_yuan)} />
        <Info label="控股要求" value={valueLabel('yes_no_like', intent.requires_control)} />
        <Info label="并表要求" value={valueLabel('yes_no_like', intent.requires_consolidation)} />
        <Info label="股权比例" value={intent.equity_ratio_summary} />
        <Info label="交易方式" value={transactionText(intent)} />
        <Info label="溢价要求" value={intent.premium_tolerance_summary || percentText(intent.max_premium_rate)} />
        <Info label="负债率要求" value={intent.debt_ratio_requirement_summary || percentText(intent.max_debt_ratio)} />
      </div>

      <SectionTitle>偏好、排除与待确认</SectionTitle>
      <div className="space-y-3">
        <Info label="需求摘要" value={intent.intent_summary} wide />
        <Info label="优先条件" value={intent.priority_summary} wide />
        <Info label="其他偏好" value={intent.preference_summary} wide />
        <Info label="产业优势" value={intent.buyer_industry_advantage_summary} wide />
        <Info label="风险容忍" value={intent.major_risk_tolerance_summary} wide />
        <Info label="排除项" value={intent.negative_summary} wide />
        <Info label="待确认" value={intent.unknown_summary} wide />
      </div>

      <SectionTitle>原始需求材料</SectionTitle>
      <p className="max-h-72 overflow-y-auto whitespace-pre-wrap bg-gray-50 px-4 py-3 text-sm leading-6 text-gray-700">
        {intent.raw_requirement_text || '暂无原始需求材料'}
      </p>
    </div>
  );
}

export function BuyerInfo({ party, onSaved }: { party: BuyerParty; onSaved?: (party: BuyerParty) => void }) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<Partial<BuyerPartyCreate>>(() => partyDraft(party));

  useEffect(() => setDraft(partyDraft(party)), [party]);

  const save = async () => {
    setSaving(true);
    try {
      const updated = await buyerParties.update(party.id, {
        buyer_name: draft.buyer_name?.trim() || party.buyer_name,
        legal_name: nullIfEmpty(draft.legal_name),
        buyer_type: nullIfEmpty(draft.buyer_type),
        group_name: nullIfEmpty(draft.group_name),
        listed_status: draft.listed_status || 'unknown',
        region_province: nullIfEmpty(draft.region_province),
        region_city: nullIfEmpty(draft.region_city),
        main_business: nullIfEmpty(draft.main_business),
        capital_strength_summary: nullIfEmpty(draft.capital_strength_summary),
        profile_summary: nullIfEmpty(draft.profile_summary),
        notes: nullIfEmpty(draft.notes),
      });
      onSaved?.(updated);
      setEditing(false);
    } catch (error) {
      alert(error instanceof Error ? error.message : '保存买家资料失败');
    } finally {
      setSaving(false);
    }
  };

  if (!editing) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <p className="text-xs text-gray-500">买家资料由用户手工维护，不参与需求解析。</p>
          <button type="button" onClick={() => setEditing(true)} className="border border-gray-200 px-3 py-1.5 text-xs text-gray-700 hover:border-brand-500 hover:text-brand-700">
            编辑资料
          </button>
        </div>
        <div className="grid grid-cols-1 gap-x-10 gap-y-3 md:grid-cols-2">
          <Info label="买家名称" value={party.buyer_name} />
          <Info label="法人全称" value={party.legal_name} />
          <Info label="买家类型" value={party.buyer_type ? valueLabel('buyer_type', party.buyer_type) : null} />
          <Info label="所属集团" value={party.group_name} />
          <Info label="所在地区" value={`${party.region_province || ''}${party.region_city || ''}`} />
          <Info label="上市状态" value={valueLabel('listed_status', party.listed_status)} />
        </div>
        <div className="space-y-3">
          <Info label="主营业务" value={party.main_business} wide />
          <Info label="资金实力/规模" value={party.capital_strength_summary} wide />
          <Info label="资料摘要" value={party.profile_summary} wide />
          <Info label="备注" value={party.notes} wide />
        </div>
      </div>
    );
  }

  const setField = (key: keyof BuyerPartyCreate, value: string) => setDraft((current) => ({ ...current, [key]: value }));
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <EditField label="买家名称"><input className="input" value={draft.buyer_name || ''} onChange={(event) => setField('buyer_name', event.target.value)} /></EditField>
        <EditField label="法人全称"><input className="input" value={draft.legal_name || ''} onChange={(event) => setField('legal_name', event.target.value)} /></EditField>
        <EditField label="买家类型"><input className="input" value={draft.buyer_type || ''} onChange={(event) => setField('buyer_type', event.target.value)} /></EditField>
        <EditField label="所属集团"><input className="input" value={draft.group_name || ''} onChange={(event) => setField('group_name', event.target.value)} /></EditField>
        <EditField label="省份"><input className="input" value={draft.region_province || ''} onChange={(event) => setField('region_province', event.target.value)} /></EditField>
        <EditField label="城市"><input className="input" value={draft.region_city || ''} onChange={(event) => setField('region_city', event.target.value)} /></EditField>
        <EditField label="上市状态">
          <select className="input" value={draft.listed_status || 'unknown'} onChange={(event) => setField('listed_status', event.target.value)}>
            <option value="unknown">未知</option><option value="listed">已上市</option><option value="unlisted">未上市</option><option value="pre_ipo">拟上市</option>
          </select>
        </EditField>
      </div>
      <EditField label="主营业务"><textarea className="input min-h-20 resize-y" value={draft.main_business || ''} onChange={(event) => setField('main_business', event.target.value)} /></EditField>
      <EditField label="资金实力/规模"><textarea className="input min-h-20 resize-y" value={draft.capital_strength_summary || ''} onChange={(event) => setField('capital_strength_summary', event.target.value)} /></EditField>
      <EditField label="资料摘要"><textarea className="input min-h-20 resize-y" value={draft.profile_summary || ''} onChange={(event) => setField('profile_summary', event.target.value)} /></EditField>
      <EditField label="备注"><textarea className="input min-h-24 resize-y" value={draft.notes || ''} onChange={(event) => setField('notes', event.target.value)} /></EditField>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={() => { setDraft(partyDraft(party)); setEditing(false); }} className="border border-gray-200 px-4 py-2 text-sm text-gray-700">取消</button>
        <button type="button" onClick={() => void save()} disabled={saving} className="bg-brand-600 px-4 py-2 text-sm text-white disabled:opacity-50">{saving ? '保存中' : '保存'}</button>
      </div>
    </div>
  );
}

function IntentAttachments({ intentId }: { intentId: string }) {
  const [items, setItems] = useState<AttachmentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await attachments.list({ entity_type: 'buyer_intent', entity_id: intentId, limit: 100 }));
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '附件读取失败');
    } finally {
      setLoading(false);
    }
  }, [intentId]);

  useEffect(() => { void load(); }, [load]);

  const download = async (item: AttachmentItem) => {
    setDownloadingId(item.id);
    try {
      const response = await attachments.download(item.id);
      const url = window.URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = item.file_name || 'attachment';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
    } catch (downloadError) {
      alert(downloadError instanceof Error ? downloadError.message : '下载失败');
    } finally {
      setDownloadingId(null);
    }
  };

  if (loading) return <LoadingText text="正在读取附件" />;
  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!items.length) return <EmptyState title="暂无附件" description="录入当前并购需求更新时上传的文件会自动出现在这里。" />;
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">共 {items.length} 个附件</p>
        <button type="button" onClick={() => void load()} className="inline-flex items-center gap-1.5 border border-gray-200 px-2.5 py-1.5 text-xs text-gray-600 hover:border-brand-500 hover:text-brand-700">
          <RefreshCw className="h-3.5 w-3.5" />刷新
        </button>
      </div>
      <div className="divide-y divide-gray-100 border border-gray-100">
        {items.map((item) => (
          <div key={item.id} className="flex items-center justify-between gap-4 px-4 py-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2"><FileText className="h-4 w-4 shrink-0 text-gray-400" /><p className="truncate text-sm font-medium text-gray-900">{item.file_name}</p><AttachmentStatus status={item.parse_status} /></div>
              <p className="mt-1 text-xs text-gray-400">{item.mime_type || item.file_type || '未知类型'} · {formatBytes(item.file_size)} · {formatDateTime(item.uploaded_at)}</p>
            </div>
            <button type="button" onClick={() => void download(item)} disabled={downloadingId === item.id} className="inline-flex shrink-0 items-center gap-1.5 border border-gray-200 px-2.5 py-1.5 text-xs text-gray-600 hover:border-brand-500 hover:text-brand-700 disabled:opacity-50">
              {downloadingId === item.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}下载
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function IntentFollowUps({ intentId, items, onRefresh }: { intentId: string; items: BuyerIntentFollowUp[]; onRefresh?: () => void | Promise<void> }) {
  const remove = async (followUpId: string) => {
    if (!window.confirm('确认删除这条跟进记录？')) return;
    try {
      await buyerIntents.deleteFollowUp(intentId, followUpId);
      await onRefresh?.();
    } catch (error) {
      alert(error instanceof Error ? error.message : '删除跟进记录失败');
    }
  };
  if (!items.length) return <EmptyState title="暂无跟进记录" description="录入当前需求的沟通、推荐、反馈或下一步后，会自动沉淀在这里。" />;
  return (
    <div className="divide-y divide-gray-100">
      {items.map((item) => (
        <article key={item.id} className="flex items-start gap-4 py-4">
          <span className="w-32 shrink-0 font-mono text-xs text-gray-400">{formatDateTime(item.occurred_at)}</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
              {item.contact_name ? <span>联系人：{item.contact_name}</span> : null}
              <span>录入人：{item.created_by_name || '-'}</span>
            </div>
            <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-gray-800">{item.content}</p>
            {item.next_step ? <p className="mt-2 text-xs text-brand-700">下一步：{item.next_step}</p> : null}
            {item.next_follow_up_at ? <p className="mt-1 text-xs text-gray-500">下次跟进：{formatDateTime(item.next_follow_up_at)}</p> : null}
          </div>
          <button type="button" onClick={() => void remove(item.id)} className="shrink-0 text-xs text-gray-400 hover:text-red-600">删除</button>
        </article>
      ))}
    </div>
  );
}

function SectionTitle({ children }: { children: ReactNode }) { return <h3 className="text-xs font-semibold text-gray-500">{children}</h3>; }
function Info({ label, value, wide = false }: { label: string; value: string | number | null | undefined; wide?: boolean }) { return <div className={`flex gap-3 ${wide ? 'items-start' : 'items-baseline'}`}><span className="w-24 shrink-0 text-xs text-gray-500">{label}</span><span className="min-w-0 whitespace-pre-wrap text-sm text-gray-800">{value || '-'}</span></div>; }
function EditField({ label, children }: { label: string; children: ReactNode }) { return <label className="block"><span className="mb-1 block text-xs font-medium text-gray-600">{label}</span>{children}</label>; }
function LoadingText({ text }: { text: string }) { return <div className="flex items-center justify-center py-12 text-sm text-gray-400"><Loader2 className="mr-2 h-4 w-4 animate-spin" />{text}</div>; }
function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) { return <div className="border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><p>{message}</p><button type="button" onClick={onRetry} className="mt-2 text-xs font-medium underline">重新加载</button></div>; }
function EmptyState({ title, description }: { title: string; description: string }) { return <div className="py-12 text-center"><Search className="mx-auto h-8 w-8 text-gray-300" /><p className="mt-2 text-sm text-gray-500">{title}</p><p className="mt-1 text-xs text-gray-400">{description}</p></div>; }

function AttachmentStatus({ status }: { status: string }) {
  const labels: Record<string, string> = { pending: '等待解析', parsing: '解析中', parsed: '已解析', failed: '解析失败', skipped: '无需解析' };
  const color = status === 'failed' ? 'bg-red-50 text-red-700' : status === 'parsing' || status === 'pending' ? 'bg-blue-50 text-blue-700' : 'bg-gray-100 text-gray-600';
  return <span className={`shrink-0 px-1.5 py-0.5 text-[11px] ${color}`}>{labels[status] || status}</span>;
}

function partyDraft(party: BuyerParty): Partial<BuyerPartyCreate> { return { buyer_name: party.buyer_name, legal_name: party.legal_name || '', buyer_type: party.buyer_type || '', group_name: party.group_name || '', listed_status: party.listed_status || 'unknown', region_province: party.region_province || '', region_city: party.region_city || '', main_business: party.main_business || '', capital_strength_summary: party.capital_strength_summary || '', profile_summary: party.profile_summary || '', notes: party.notes || '' }; }
function nullIfEmpty(value: string | null | undefined): string | null { return value?.trim() || null; }
function hasStructuredIntentFields(intent: BuyerIntent): boolean { return Boolean(intent.intent_summary || intent.industry_primary || intent.region_scope_summary || intent.min_net_profit_yuan); }
function listingRequirementLabel(intent: BuyerIntent): string { const status = intent.preferred_listed_status && intent.preferred_listed_status !== 'unknown' ? valueLabel('preferred_listed_status', intent.preferred_listed_status) : null; return [status, intent.listing_board_requirement_summary, intent.financing_stage_requirement_summary].filter(Boolean).join(' / ') || '-'; }
function valuationRangeLabel(intent: BuyerIntent): string { const min = moneyText(intent.min_valuation_yuan); const max = moneyText(intent.max_valuation_yuan); return min && max ? `${min}-${max}` : min ? `≥${min}` : max ? `≤${max}` : '-'; }
function marketCapRangeLabel(intent: BuyerIntent): string { if (intent.market_cap_range_summary) return intent.market_cap_range_summary; const min = moneyText(intent.min_market_cap_yuan); const max = moneyText(intent.max_market_cap_yuan); return min && max ? `${min}-${max}` : min ? `≥${min}` : max ? `≤${max}` : '-'; }
function transactionText(intent: BuyerIntent): string | null { if (intent.transaction_type) return intent.transaction_type; return Array.isArray(intent.transaction_types_json) ? intent.transaction_types_json.join('、') : null; }
function moneyText(value: string | number | null | undefined): string | null { if (value === null || value === undefined || value === '') return null; const number = Number(value); if (!Number.isFinite(number)) return null; if (Math.abs(number) < 10000) return `${number.toFixed(0)}元`; if (Math.abs(number) < 100000000) return `${(number / 10000).toFixed(0)}万`; return `${(number / 100000000).toFixed(1)}亿`; }
function numberText(value: string | number | null | undefined): string | null { return value === null || value === undefined || value === '' ? null : Number(value).toFixed(0); }
function percentText(value: string | number | null | undefined): string | null { return value === null || value === undefined || value === '' ? null : `${Number(value).toFixed(0)}%`; }
function formatBytes(value: number | null): string { if (value === null) return '未知大小'; if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`; if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`; return `${value} B`; }
function formatDateTime(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }); }
