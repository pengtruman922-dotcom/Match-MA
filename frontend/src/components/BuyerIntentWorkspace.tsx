import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Check,
  Download,
  FileText,
  Loader2,
  Pencil,
  RefreshCw,
  Search,
  X,
} from 'lucide-react';
import { attachments, buyerParties, indicatorRegistry } from '../lib/api';
import type {
  AttachmentItem,
  BuyerIntent,
  BuyerIntentParseStatus,
  BuyerParty,
  BuyerPartyCreate,
  IndicatorRegistryResponse,
} from '../types/api';
import UpdateHistory from './UpdateHistory';
import ProgressPanel from '../features/relations/ProgressPanel';
import BuyerIntentRequirements from './BuyerIntentRequirements';
import AdministrativeAreaPicker, { type AdministrativeAreaValue } from './AdministrativeAreaPicker';
import { partyLocationText, partyMarketValue, partyMarketValueField, parseYuanInput } from '../features/buyers/presentation';
import { formatYuan } from '../lib/format';
import { gradeClass, intentGrade, intentGradeLabel } from '../lib/entityGrade';

export type BuyerWorkspaceTab = 'intent' | 'buyer' | 'progress' | 'attachments' | 'history';

interface Props {
  intent: BuyerIntent;
  party: BuyerParty | null;
  parseStatus: BuyerIntentParseStatus | null;
  activeTab: BuyerWorkspaceTab;
  onTabChange: (tab: BuyerWorkspaceTab) => void;
  /** 撮合看板 `?relation=` 深链接，透传给「推进」tab 的 ProgressPanel。 */
  progressOpenRelationId?: string | null;
  onProgressDrawerClose?: () => void;
  historyRefreshKey?: number;
  onPartySaved?: (party: BuyerParty) => void;
  onIntentSaved?: (intent: BuyerIntent) => void;
  onIntentRefresh?: () => void | Promise<void>;
}

const TABS: Array<{ key: BuyerWorkspaceTab; label: string }> = [
  { key: 'intent', label: '需求信息' },
  { key: 'buyer', label: '买家信息' },
  { key: 'progress', label: '推进' },
  { key: 'attachments', label: '附件与证据' },
  { key: 'history', label: '更新记录' },
];

export default function BuyerIntentWorkspace({
  intent,
  party,
  parseStatus,
  activeTab,
  onTabChange,
  progressOpenRelationId = null,
  onProgressDrawerClose,
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
        {activeTab === 'intent' ? <BuyerIntentRequirements intent={intent} parseStatus={parseStatus} onRefresh={onIntentRefresh} /> : null}
        {activeTab === 'buyer' ? (
          party ? (
            <BuyerInfo party={party} onPartySaved={onPartySaved} />
          ) : (
            <EmptyState title="当前需求未关联买家" description="可在买家管理中补充关联关系。" />
          )
        ) : null}
        {activeTab === 'progress' ? (
          <ProgressPanel
            side="buyer_intent"
            entityId={intent.id}
            initialOpenId={progressOpenRelationId}
            onDrawerClose={onProgressDrawerClose}
          />
        ) : null}
        {activeTab === 'attachments' ? <IntentAttachments intentId={intent.id} onIntentRefresh={onIntentRefresh} /> : null}
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

export function IntentStatusBadge({ item }: { item: BuyerIntent }) {
  return (
    <span className={`px-2 py-0.5 text-xs font-medium ${gradeClass(intentGrade(item))}`}>
      {intentGradeLabel(item)}
    </span>
  );
}

type BuyerInfoField =
  | 'buyer_name'
  | 'location'
  | 'ownership_type'
  | 'listing'
  | 'contact_name'
  | 'contact_info'
  | 'our_contact_name'
  | 'business_tags'
  | 'business_summary'
  | 'market_value'
  | 'operating'
  | 'supplementary_summary'
  | 'notes';

/** 上市信息是一行三个字段：状态决定后两个有没有意义。 */
type ListingDraft = { listed_status: string; listing_exchange: string; stock_code: string };
/** 市值与估值是一个展示位，编辑态也是一个位置：各自的数字与时间成对出现。 */
type MarketValueDraft = { market_cap: string; market_cap_as_of: string; valuation: string; valuation_date: string };
type OperatingDraft = { revenue: string; cash_flow: string; period: string };

export function BuyerInfo({
  party,
  onPartySaved,
}: {
  party: BuyerParty;
  onPartySaved?: (party: BuyerParty) => void;
}) {
  const [editingField, setEditingField] = useState<BuyerInfoField | null>(null);
  const [saving, setSaving] = useState(false);
  const [textDraft, setTextDraft] = useState('');
  const [locationDraft, setLocationDraft] = useState<AdministrativeAreaValue>({ province: '' });
  const [listingDraft, setListingDraft] = useState<ListingDraft>({ listed_status: 'unknown', listing_exchange: '', stock_code: '' });
  const [marketDraft, setMarketDraft] = useState<MarketValueDraft>({ market_cap: '', market_cap_as_of: '', valuation: '', valuation_date: '' });
  const [operatingDraft, setOperatingDraft] = useState<OperatingDraft>({ revenue: '', cash_flow: '', period: '' });
  // 枚举中文名与字段中文名都从指标注册表下发：注册表改一处，界面跟着变。
  const [registry, setRegistry] = useState<IndicatorRegistryResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    indicatorRegistry.list('buyer_party').then((value) => { if (!cancelled) setRegistry(value); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);
  useEffect(() => setEditingField(null), [party.id]);

  const label = (column: string, fallback: string) =>
    registry?.indicators.find((item) => item.column === column)?.label || fallback;
  const options = (column: string) =>
    registry?.indicators.find((item) => item.column === column)?.enum_options || [];
  const enumText = (column: string, value: string | null) => {
    if (!value || value === 'unknown') return '';
    return options(column).find((option) => option.value === value)?.label || value;
  };

  const startEditing = (field: BuyerInfoField) => {
    if (field === 'buyer_name') setTextDraft(party.buyer_name);
    if (field === 'location') setLocationDraft({ province: party.location_province || '', city: party.location_city || undefined, district: party.location_district || undefined });
    if (field === 'ownership_type') setTextDraft(party.ownership_type || 'unknown');
    if (field === 'listing') setListingDraft({ listed_status: party.listed_status || 'unknown', listing_exchange: party.listing_exchange || '', stock_code: party.stock_code || '' });
    if (field === 'contact_name') setTextDraft(party.contact_name || '');
    if (field === 'contact_info') setTextDraft(contactInfoText(party.contact_info_json));
    if (field === 'our_contact_name') setTextDraft(party.our_contact_name || '');
    if (field === 'business_tags') setTextDraft((party.business_tags_json || []).join('、'));
    if (field === 'business_summary') setTextDraft(party.business_summary || '');
    if (field === 'market_value') setMarketDraft({ market_cap: moneyDraft(party.market_cap_yuan), market_cap_as_of: party.market_cap_as_of || '', valuation: moneyDraft(party.valuation_yuan), valuation_date: party.valuation_date || '' });
    if (field === 'operating') setOperatingDraft({ revenue: moneyDraft(party.current_revenue_yuan), cash_flow: moneyDraft(party.current_operating_cash_flow_yuan), period: party.financial_period_label || '' });
    if (field === 'supplementary_summary') setTextDraft(party.supplementary_summary || '');
    if (field === 'notes') setTextDraft(party.notes || '');
    setEditingField(field);
  };

  const saveField = async () => {
    if (!editingField) return;
    setSaving(true);
    try {
      onPartySaved?.(await buyerParties.update(party.id, buildPartyPatch(editingField, {
        textDraft,
        locationDraft,
        listingDraft,
        marketDraft,
        operatingDraft,
      })));
      setEditingField(null);
    } catch (error) {
      alert(error instanceof Error ? error.message : '保存买家信息失败');
    } finally {
      setSaving(false);
    }
  };

  const rowProps = { editingField, saving, onEdit: startEditing, onSave: saveField, onCancel: () => setEditingField(null) };
  const marketValue = partyMarketValue(party);
  const marketMode = partyMarketValueField(party);

  return (
    <div>
      <p className="mb-3 text-xs text-gray-500">以下均为买家主体资料，描述的是这家买家自己。编辑后会同步到同一买家的所有需求；本次收购需求的行业和目标地区在“需求信息”中维护。</p>
      <div className="space-y-5">
        <BuyerInfoGroup title="基本信息">
          <BuyerInfoRow label={label('buyer_name', '买家名称')} value={party.buyer_name} field="buyer_name" {...rowProps}>
            <input className="input" value={textDraft} onChange={(event) => setTextDraft(event.target.value)} autoFocus />
          </BuyerInfoRow>
          <BuyerInfoRow label={label('location_province', '所在地')} value={partyLocationText(party)} field="location" {...rowProps}>
            <AdministrativeAreaPicker value={locationDraft} onChange={setLocationDraft} />
          </BuyerInfoRow>
          <BuyerInfoRow label={label('ownership_type', '企业性质')} value={enumText('ownership_type', party.ownership_type)} field="ownership_type" {...rowProps}>
            <select className="input" value={textDraft} onChange={(event) => setTextDraft(event.target.value)} autoFocus>
              {options('ownership_type').map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
            <p className="text-xs text-gray-400">央企与地方国企同选「国企」，区别写进业务说明；基金按出资方性质选。</p>
          </BuyerInfoRow>
          <BuyerInfoRow label={label('listed_status', '上市状态')} value={listingText(party, enumText)} field="listing" {...rowProps}>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <select className="input" value={listingDraft.listed_status} onChange={(event) => setListingDraft({ ...listingDraft, listed_status: event.target.value })} autoFocus>
                {options('listed_status').map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
              <select className="input" value={listingDraft.listing_exchange} onChange={(event) => setListingDraft({ ...listingDraft, listing_exchange: event.target.value })}>
                <option value="">上市地（可不填）</option>
                {options('listing_exchange').map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
              <input className="input" value={listingDraft.stock_code} onChange={(event) => setListingDraft({ ...listingDraft, stock_code: event.target.value })} placeholder="股票代码" />
            </div>
          </BuyerInfoRow>
          <BuyerInfoRow label={label('contact_name', '联系人')} value={party.contact_name || ''} field="contact_name" {...rowProps}>
            <input className="input" value={textDraft} onChange={(event) => setTextDraft(event.target.value)} autoFocus />
          </BuyerInfoRow>
          <BuyerInfoRow label={label('contact_info_json', '联系方式')} value={contactInfoText(party.contact_info_json)} field="contact_info" {...rowProps}>
            <textarea className="input min-h-20 resize-y" value={textDraft} onChange={(event) => setTextDraft(event.target.value)} placeholder="电话、邮箱、微信等" autoFocus />
          </BuyerInfoRow>
          <BuyerInfoRow label={label('our_contact_name', '我方对接人')} value={party.our_contact_name || ''} field="our_contact_name" {...rowProps}>
            <input className="input" value={textDraft} onChange={(event) => setTextDraft(event.target.value)} placeholder="我方负责对接这家买家的人" autoFocus />
          </BuyerInfoRow>
        </BuyerInfoGroup>

        <BuyerInfoGroup title="业务信息">
          <BuyerInfoRow label={label('business_tags_json', '业务标签')} value={(party.business_tags_json || []).join('、')} field="business_tags" {...rowProps}>
            <input className="input" value={textDraft} onChange={(event) => setTextDraft(event.target.value)} placeholder="多个标签用顿号、逗号或换行分隔，5 个以内" autoFocus />
          </BuyerInfoRow>
          <BuyerInfoRow label={label('business_summary', '业务说明')} value={party.business_summary || ''} field="business_summary" {...rowProps}>
            <textarea className="input min-h-28 resize-y" value={textDraft} onChange={(event) => setTextDraft(event.target.value)} placeholder="这家买家自己做什么、在产业链什么位置，200 字左右" autoFocus />
          </BuyerInfoRow>
        </BuyerInfoGroup>

        <BuyerInfoGroup title="财务信息">
          <BuyerInfoRow
            label={marketValue?.label || (marketMode === 'market_cap' ? '市值' : '估值')}
            value={marketValue ? `${marketValue.value}${marketValue.asOf ? `（${marketValue.asOf}）` : ''}` : ''}
            field="market_value"
            {...rowProps}
          >
            <div className="space-y-2">
              {marketMode !== 'valuation' ? (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <input className="input" value={marketDraft.market_cap} onChange={(event) => setMarketDraft({ ...marketDraft, market_cap: event.target.value })} placeholder="市值，如 32.6亿" autoFocus />
                  <input className="input" type="date" value={marketDraft.market_cap_as_of} onChange={(event) => setMarketDraft({ ...marketDraft, market_cap_as_of: event.target.value })} />
                </div>
              ) : null}
              {marketMode !== 'market_cap' ? (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <input className="input" value={marketDraft.valuation} onChange={(event) => setMarketDraft({ ...marketDraft, valuation: event.target.value })} placeholder="估值，如 12亿" />
                  <input className="input" value={marketDraft.valuation_date} onChange={(event) => setMarketDraft({ ...marketDraft, valuation_date: event.target.value })} placeholder="估值时点，如 2025年一季度" />
                </div>
              ) : null}
              <p className="text-xs text-gray-400">上市买家看市值（带行情日期），非上市/拟上市看估值（带时点）。金额可写「32.6亿」「3260万」。</p>
            </div>
          </BuyerInfoRow>
          <BuyerInfoRow label="营收 / 经营现金流" value={operatingText(party)} field="operating" {...rowProps}>
            <div className="space-y-2">
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <input className="input" value={operatingDraft.revenue} onChange={(event) => setOperatingDraft({ ...operatingDraft, revenue: event.target.value })} placeholder="营收，如 58亿" autoFocus />
                <input className="input" value={operatingDraft.cash_flow} onChange={(event) => setOperatingDraft({ ...operatingDraft, cash_flow: event.target.value })} placeholder="经营现金流，如 4.2亿" />
              </div>
              <input className="input" value={operatingDraft.period} onChange={(event) => setOperatingDraft({ ...operatingDraft, period: event.target.value })} placeholder="财务期间，如 2024年度（两个数字共用）" />
            </div>
          </BuyerInfoRow>
        </BuyerInfoGroup>

        <BuyerInfoGroup title="其他">
          <BuyerInfoRow label={label('supplementary_summary', '补充信息')} value={party.supplementary_summary || ''} field="supplementary_summary" {...rowProps}>
            <textarea className="input min-h-28 resize-y" value={textDraft} onChange={(event) => setTextDraft(event.target.value)} placeholder="风险或其他可能影响并购的企业重要信息，会进入推荐上下文" autoFocus />
          </BuyerInfoRow>
          <BuyerInfoRow label="运营备注" value={party.notes || ''} field="notes" {...rowProps}>
            <textarea className="input min-h-28 resize-y" value={textDraft} onChange={(event) => setTextDraft(event.target.value)} placeholder="内部备注，不进入推荐上下文" autoFocus />
          </BuyerInfoRow>
        </BuyerInfoGroup>
      </div>
    </div>
  );
}

function BuyerInfoGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h4 className="mb-2 text-xs font-semibold text-gray-700">{title}</h4>
      <div className="divide-y divide-gray-100 border border-gray-100 px-4">{children}</div>
    </section>
  );
}

/** 数字输入框的初值：显示成「32.6亿」而不是 3260000000，因为回填的也是这个格式。 */
function moneyDraft(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '';
  return formatYuan(value);
}

function listingText(party: BuyerParty, enumText: (column: string, value: string | null) => string): string {
  const status = enumText('listed_status', party.listed_status);
  if (!status) return '';
  const suffix = [enumText('listing_exchange', party.listing_exchange), party.stock_code].filter(Boolean).join(' ');
  return suffix ? `${status}（${suffix}）` : status;
}

/** 财务数字必须带时间一起显示：没有时间的财务数字是不可用的。 */
function operatingText(party: BuyerParty): string {
  const parts = [
    party.current_revenue_yuan === null || party.current_revenue_yuan === undefined ? null : `营收 ${formatYuan(party.current_revenue_yuan)}`,
    party.current_operating_cash_flow_yuan === null || party.current_operating_cash_flow_yuan === undefined ? null : `经营现金流 ${formatYuan(party.current_operating_cash_flow_yuan)}`,
  ].filter(Boolean);
  if (!parts.length) return '';
  return `${parts.join('，')}${party.financial_period_label ? `（${party.financial_period_label}）` : ''}`;
}

/**
 * 每个可编辑位对应的 PATCH 载荷。抽出来是因为一个「位」可能写多列
 * （上市状态写三列、市值/估值写四列），逻辑写在 JSX 里会看不出来。
 */
function buildPartyPatch(
  field: BuyerInfoField,
  drafts: {
    textDraft: string;
    locationDraft: AdministrativeAreaValue;
    listingDraft: ListingDraft;
    marketDraft: MarketValueDraft;
    operatingDraft: OperatingDraft;
  },
): Partial<BuyerPartyCreate> {
  const { textDraft, locationDraft, listingDraft, marketDraft, operatingDraft } = drafts;
  switch (field) {
    case 'buyer_name': {
      const buyerName = textDraft.trim();
      if (!buyerName) throw new Error('买家名称不能为空');
      return { buyer_name: buyerName };
    }
    case 'location':
      return {
        location_province: nullIfEmpty(locationDraft.province),
        location_city: nullIfEmpty(locationDraft.city),
        location_district: nullIfEmpty(locationDraft.district),
      };
    case 'ownership_type':
      return { ownership_type: textDraft || 'unknown' };
    case 'listing':
      return {
        listed_status: listingDraft.listed_status || 'unknown',
        listing_exchange: nullIfEmpty(listingDraft.listing_exchange),
        stock_code: nullIfEmpty(listingDraft.stock_code),
      };
    case 'contact_name':
      return { contact_name: nullIfEmpty(textDraft) };
    case 'contact_info':
      return { contact_info_json: textDraft.trim() ? { text: textDraft.trim() } : {} };
    case 'our_contact_name':
      return { our_contact_name: nullIfEmpty(textDraft) };
    case 'business_tags':
      return { business_tags_json: splitTags(textDraft) };
    case 'business_summary':
      return { business_summary: nullIfEmpty(textDraft) };
    case 'market_value':
      return {
        market_cap_yuan: parseYuanInput(marketDraft.market_cap),
        market_cap_as_of: nullIfEmpty(marketDraft.market_cap_as_of),
        valuation_yuan: parseYuanInput(marketDraft.valuation),
        valuation_date: nullIfEmpty(marketDraft.valuation_date),
      };
    case 'operating':
      return {
        current_revenue_yuan: parseYuanInput(operatingDraft.revenue),
        current_operating_cash_flow_yuan: parseYuanInput(operatingDraft.cash_flow),
        financial_period_label: nullIfEmpty(operatingDraft.period),
      };
    case 'supplementary_summary':
      return { supplementary_summary: nullIfEmpty(textDraft) };
    case 'notes':
      return { notes: nullIfEmpty(textDraft) };
  }
}

function BuyerInfoRow({
  label,
  value,
  field,
  editingField,
  saving,
  disabled = false,
  onEdit,
  onSave,
  onCancel,
  children,
}: {
  label: string;
  value: string;
  field: BuyerInfoField;
  editingField: BuyerInfoField | null;
  saving: boolean;
  disabled?: boolean;
  onEdit: (field: BuyerInfoField) => void;
  onSave: () => Promise<void>;
  onCancel: () => void;
  children: ReactNode;
}) {
  const editing = editingField === field;
  return (
    <div className="py-3">
      {editing ? (
        <div className="space-y-3">
          <p className="text-xs font-medium text-gray-600">{label}</p>
          {children}
          <div className="flex justify-end gap-2">
            <button type="button" disabled={saving} onClick={() => void onSave()} className="inline-flex items-center gap-1 bg-brand-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}保存</button>
            <button type="button" disabled={saving} onClick={onCancel} className="inline-flex items-center gap-1 border border-gray-200 px-3 py-1.5 text-xs text-gray-600"><X className="h-3.5 w-3.5" />取消</button>
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-3">
          <span className="w-24 shrink-0 text-xs text-gray-500">{label}</span>
          <span className={`min-w-0 flex-1 whitespace-pre-wrap text-sm ${value ? 'text-gray-800' : 'text-gray-300'}`}>{value || (disabled ? '录入需求后维护' : '未填写')}</span>
          <button type="button" title={`编辑${label}`} disabled={disabled} onClick={() => onEdit(field)} className="p-1.5 text-gray-400 hover:bg-gray-100 hover:text-brand-700 disabled:cursor-not-allowed disabled:opacity-30"><Pencil className="h-3.5 w-3.5" /></button>
        </div>
      )}
    </div>
  );
}

function IntentAttachments({ intentId, onIntentRefresh }: { intentId: string; onIntentRefresh?: () => void | Promise<void> }) {
  const [items, setItems] = useState<AttachmentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);

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
  useEffect(() => {
    if (!items.some((item) => ['pending', 'processing'].includes(item.content_extraction_status))) return;
    const timer = window.setInterval(() => { void load(); void onIntentRefresh?.(); }, 2500);
    return () => window.clearInterval(timer);
  }, [items, load, onIntentRefresh]);

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

  const reprocess = async (item: AttachmentItem) => {
    setRetryingId(item.id);
    try {
      await attachments.reprocess(item.id);
      await Promise.all([load(), Promise.resolve(onIntentRefresh?.())]);
    } catch (retryError) {
      alert(retryError instanceof Error ? retryError.message : '重新处理失败');
    } finally {
      setRetryingId(null);
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
              <div className="flex items-center gap-2"><FileText className="h-4 w-4 shrink-0 text-gray-400" /><p className="truncate text-sm font-medium text-gray-900">{item.file_name}</p><AttachmentStatus item={item} /></div>
              <p className="mt-1 text-xs text-gray-400">{attachmentKindLabel(item)} · {formatBytes(item.file_size)} · {formatDateTime(item.uploaded_at)}</p>
              {item.error_message ? <p className="mt-1 max-w-2xl text-xs text-red-600">{item.error_message}</p> : null}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {item.recoverable ? <button type="button" onClick={() => void reprocess(item)} disabled={retryingId === item.id} className="inline-flex items-center gap-1.5 border border-red-200 px-2.5 py-1.5 text-xs text-red-700 hover:bg-red-50 disabled:opacity-50">{retryingId === item.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}重新处理</button> : null}
              <button type="button" onClick={() => void download(item)} disabled={downloadingId === item.id} className="inline-flex items-center gap-1.5 border border-gray-200 px-2.5 py-1.5 text-xs text-gray-600 hover:border-brand-500 hover:text-brand-700 disabled:opacity-50">
                {downloadingId === item.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}下载
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function LoadingText({ text }: { text: string }) { return <div className="flex items-center justify-center py-12 text-sm text-gray-400"><Loader2 className="mr-2 h-4 w-4 animate-spin" />{text}</div>; }
function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) { return <div className="border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><p>{message}</p><button type="button" onClick={onRetry} className="mt-2 text-xs font-medium underline">重新加载</button></div>; }
function EmptyState({ title, description }: { title: string; description: string }) { return <div className="py-12 text-center"><Search className="mx-auto h-8 w-8 text-gray-300" /><p className="mt-2 text-sm text-gray-500">{title}</p><p className="mt-1 text-xs text-gray-400">{description}</p></div>; }

function AttachmentStatus({ item }: { item: AttachmentItem }) {
  const labels = { pending: '等待读取', processing: '读取中', succeeded: '读取成功', failed: '读取失败', skipped: '无需读取', multimodal: '模型直读' };
  const status = item.content_extraction_status;
  const color = status === 'failed' ? 'bg-red-50 text-red-700' : status === 'processing' || status === 'pending' ? 'bg-blue-50 text-blue-700' : status === 'multimodal' ? 'bg-purple-50 text-purple-700' : 'bg-gray-100 text-gray-600';
  return <span className={`shrink-0 px-1.5 py-0.5 text-[11px] ${color}`}>{labels[status]}</span>;
}

function nullIfEmpty(value: string | null | undefined): string | null { return value?.trim() || null; }
/** 顿号、逗号、换行都算分隔符，与需求侧的标签输入同一套规则。 */
function splitTags(value: string): string[] { return [...new Set(value.split(/[、，,\n]/).map((item) => item.trim()).filter(Boolean))]; }
function contactInfoText(value: Record<string, unknown> | null | undefined): string {
  if (!value || !Object.keys(value).length) return '';
  if (typeof value.text === 'string') return value.text;
  const labels: Record<string, string> = { phone: '电话', mobile: '手机', email: '邮箱', wechat: '微信' };
  return Object.entries(value).flatMap(([key, item]) => {
    if (item === null || item === undefined || item === '') return [];
    const text = Array.isArray(item) ? item.join('、') : typeof item === 'object' ? JSON.stringify(item) : String(item);
    return [`${labels[key] || key}：${text}`];
  }).join('\n');
}
function attachmentKindLabel(item: AttachmentItem): string {
  const extension = (item.file_type || item.file_name.split('.').pop() || '').toLowerCase();
  if (item.extraction_strategy === 'multimodal_llm_direct') return '图片 · 模型直接读取';
  if (extension === 'doc' || extension === 'docx') return `Word 文档 · ${item.extraction_strategy === 'office_text_layer' ? '本地内容读取' : '内容读取'}`;
  if (extension === 'xls' || extension === 'xlsx') return `Excel 文档 · ${item.extraction_strategy === 'office_text_layer' ? '本地内容读取' : '内容读取'}`;
  if (extension === 'ppt' || extension === 'pptx') return `PowerPoint 文档 · ${item.extraction_strategy === 'office_text_layer' ? '本地内容读取' : '内容读取'}`;
  if (item.extraction_strategy === 'doc2x_ocr') return '扫描 PDF · OCR';
  return item.mime_type || item.file_type || '未知类型';
}
function formatBytes(value: number | null): string { if (value === null) return '未知大小'; if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`; if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`; return `${value} B`; }
function formatDateTime(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }); }
