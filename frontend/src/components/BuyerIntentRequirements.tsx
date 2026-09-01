import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  AlertCircle,
  Check,
  Copy,
  Loader2,
  Pencil,
  Plus,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import { buyerIntents, fieldSources, indicatorRegistry } from '../lib/api';
import type {
  BuyerIntent,
  BuyerIntentConfirmationItem,
  BuyerIntentParseStatus,
  BuyerIntentScenario,
  BuyerIntentScenarioWrite,
  BuyerRegionConstraint,
  IndicatorMeta,
  IndicatorRegistryResponse,
  FieldValueSource,
} from '../types/api';
import { hasReadableEvidence, sourceDetailText } from '../features/shared/fieldSource';
import AdministrativeAreaPicker from './AdministrativeAreaPicker';

/**
 * 需求信息 tab（2026-09-01 方案化重构）。
 *
 * **一条需求 = 一个容器挂 1..N 个互相独立、各自完整的方案**，命中任意一个即算
 * 命中这条需求。没有公共层 —— 公共层不是「共享的便利」，是解析器猜不出某条
 * 约束属于哪一档时的兜底桶，实测生产库它与方案层的取值冲突 11 个格子。
 *
 * 三件跟着消失的东西：
 *
 * 1. **必须/优先角标**。`screening_sql.py` 是一组纯 AND，从来不区分强弱，
 *    角标写着「优先」而 SQL 照硬筛 —— 它在骗人。「优先大湾区」这类语气
 *    现在进方案的「其他要求」。
 * 2. **方案名称**。摘要就是标题（一段话说清要买什么业务、什么地域、什么规模）。
 * 3. **原始需求材料**。它在「更新记录」tab 里看，这里不重复一份。
 *
 * 单方案的需求（生产里 40/48 条）**不套方案框**，界面上不出现「方案」二字。
 */
type PendingItem = BuyerIntentConfirmationItem & { scenarioId: string | null; scopeLabel: string };

/** 门槛格子的排布：两列，左列地区与上市状态，右列财务数字。固定顺序不按有值排序 ——
 *  位置固定顾问才能形成肌肉记忆，而 10 个格子里通常只有 1-2 个有值。 */
const THRESHOLD_LAYOUT: string[][] = [
  ['required_regions_json', 'min_market_cap_yuan'],
  ['acceptable_listed_status_json', 'max_market_cap_yuan'],
  ['min_revenue_yuan', 'min_valuation_yuan'],
  ['min_net_profit_yuan', 'max_valuation_yuan'],
  ['max_pe', ''],
];
const BUSINESS_FIELDS = ['scenario_summary', 'business_tags_json', 'excluded_business_text'] as const;
const SCENARIO_FIELDS = [
  ...BUSINESS_FIELDS,
  ...THRESHOLD_LAYOUT.flat().filter(Boolean),
  'other_requirements_text',
];

export default function BuyerIntentRequirements({
  intent,
  parseStatus,
  onRefresh,
}: {
  intent: BuyerIntent;
  parseStatus: BuyerIntentParseStatus | null;
  onRefresh?: () => void | Promise<void>;
}) {
  const [scenarios, setScenarios] = useState<BuyerIntentScenario[]>([]);
  const [registry, setRegistry] = useState<IndicatorRegistryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [resolvingItem, setResolvingItem] = useState<string | null>(null);
  const [sources, setSources] = useState<FieldValueSource[]>([]);
  const [openEvidence, setOpenEvidence] = useState<FieldValueSource | null>(null);
  const [busy, setBusy] = useState(false);

  const loadScenarios = useCallback(async () => {
    setLoading(true);
    try {
      setScenarios(await buyerIntents.scenarios(intent.id));
    } finally {
      setLoading(false);
    }
  }, [intent.id]);

  useEffect(() => { void loadScenarios(); }, [loadScenarios]);
  useEffect(() => {
    fieldSources
      .list({ entity_type: 'buyer_intent', entity_id: intent.id, limit: 200 })
      .then(setSources)
      .catch(() => {});
  }, [intent.id]);
  useEffect(() => {
    indicatorRegistry.list('buyer_intent_scenario').then(setRegistry).catch(() => {});
  }, []);

  const indicatorByColumn = useMemo(() => {
    const map = new Map<string, IndicatorMeta>();
    for (const indicator of registry?.indicators || []) map.set(indicator.column, indicator);
    return map;
  }, [registry]);

  // 一个字段可能被写过多次，接口按时间倒序返回，第一条就是当前值的来源。
  const sourceByField = useMemo(() => {
    const map = new Map<string, FieldValueSource>();
    for (const source of sources) if (!map.has(source.field_path)) map.set(source.field_path, source);
    return map;
  }, [sources]);

  const pending = useMemo<PendingItem[]>(() => [
    ...(intent.needs_confirmation_json || []).map((item) => ({ ...item, scenarioId: null, scopeLabel: '需求' })),
    ...scenarios.flatMap((scenario, index) =>
      (scenario.needs_confirmation_json || []).map((item) => ({
        ...item,
        scenarioId: scenario.id,
        scopeLabel: scenarios.length > 1 ? `方案 ${index + 1}` : '需求',
      })),
    ),
  ], [intent.needs_confirmation_json, scenarios]);

  const saveScenario = useCallback(async (scenario: BuyerIntentScenario, patch: Record<string, unknown>) => {
    const payload: BuyerIntentScenarioWrite = {
      sort_order: scenario.sort_order,
      active: scenario.active,
      needs_confirmation_json: scenario.needs_confirmation_json,
      ...Object.fromEntries(SCENARIO_FIELDS.map((field) => [field, (scenario as unknown as Record<string, unknown>)[field]])),
      ...patch,
    } as BuyerIntentScenarioWrite;
    const updated = await buyerIntents.updateScenario(intent.id, scenario.id, payload);
    setScenarios((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    await onRefresh?.();
  }, [intent.id, onRefresh]);

  const addScenario = useCallback(async () => {
    setBusy(true);
    try {
      // 新方案是空的，由顾问自己填。**不提供「拆分」** —— 把一条需求的字段
      // 分配到两边需要理解原文，那件事重跑解析做得比人点几下准。
      await buyerIntents.createScenario(intent.id, {
        sort_order: scenarios.length,
        active: true,
      } as BuyerIntentScenarioWrite);
      await loadScenarios();
    } finally {
      setBusy(false);
    }
  }, [intent.id, loadScenarios, scenarios.length]);

  const copyScenario = useCallback(async (scenario: BuyerIntentScenario) => {
    setBusy(true);
    try {
      await buyerIntents.createScenario(intent.id, {
        sort_order: scenarios.length,
        active: scenario.active,
        ...Object.fromEntries(SCENARIO_FIELDS.map((field) => [field, (scenario as unknown as Record<string, unknown>)[field]])),
      } as BuyerIntentScenarioWrite);
      await loadScenarios();
    } finally {
      setBusy(false);
    }
  }, [intent.id, loadScenarios, scenarios.length]);

  const deleteScenario = useCallback(async (scenario: BuyerIntentScenario) => {
    if (scenarios.length <= 1) {
      // 删掉唯一的方案等于把这条需求的门槛全部删掉，而且不报错 ——
      // 方案化之后「需求没有方案」是不合法状态。
      window.alert('这是唯一的方案，删掉之后这条需求就没有任何要求了。请先新增一个方案。');
      return;
    }
    if (!window.confirm('删除这个方案？它的门槛和摘要会一起消失。')) return;
    setBusy(true);
    try {
      await buyerIntents.deleteScenario(intent.id, scenario.id);
      await loadScenarios();
    } finally {
      setBusy(false);
    }
  }, [intent.id, loadScenarios, scenarios.length]);

  const resolvePending = useCallback(async (item: PendingItem, action: 'apply' | 'discard', value?: unknown) => {
    const key = confirmationKey(item);
    setResolvingItem(key);
    try {
      if (item.scenarioId) {
        const scenario = scenarios.find((entry) => entry.id === item.scenarioId);
        if (!scenario) return;
        const remaining = (scenario.needs_confirmation_json || []).filter((entry) => !sameConfirmation(entry, item));
        const patch: Record<string, unknown> = { needs_confirmation_json: remaining };
        if (action === 'apply') {
          const proposed = value === undefined ? item.proposed_value : value;
          patch[item.field] = mergeProposedValue((scenario as unknown as Record<string, unknown>)[item.field], proposed);
        }
        await saveScenario(scenario, patch);
      } else {
        const remaining = (intent.needs_confirmation_json || []).filter((entry) => !sameConfirmation(entry, item));
        const patch: Record<string, unknown> = { needs_confirmation_json: remaining };
        if (action === 'apply') {
          const proposed = value === undefined ? item.proposed_value : value;
          patch[item.field] = mergeProposedValue((intent as unknown as Record<string, unknown>)[item.field], proposed);
        }
        await buyerIntents.update(intent.id, patch as Record<string, never>);
        await onRefresh?.();
      }
    } finally {
      setResolvingItem(null);
    }
  }, [intent, onRefresh, saveScenario, scenarios]);

  const modifyPending = useCallback((item: PendingItem) => {
    const initial = item.proposed_value === undefined ? '' : JSON.stringify(item.proposed_value, null, 2);
    const input = window.prompt('修改建议值。数组或对象请填写合法 JSON；普通文字可直接填写。', initial);
    if (input === null) return;
    let parsed: unknown = input;
    try { parsed = JSON.parse(input); } catch { parsed = input.trim(); }
    void resolvePending(item, 'apply', parsed);
  }, [resolvePending]);

  const failedJob = parseStatus?.latest_job?.status === 'failed' ? parseStatus.latest_job : null;
  const multi = scenarios.length > 1;

  return (
    <div className="space-y-5">
      {failedJob ? (
        <div className="flex items-start gap-2 border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div><p className="font-medium">最近一次解析失败</p><p className="mt-1 text-xs">{failedJob.error_message || '请重新发起解析。'}</p></div>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
          {multi ? <span className="font-medium text-gray-700">{scenarios.length} 个方案</span> : null}
          {multi ? <span>满足任意一个方案即算命中这条需求</span> : null}
          {pending.length ? <StateBadge tone="amber" text={`${pending.length} 项需要确认`} /> : null}
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void addScenario()}
          className="inline-flex items-center gap-1 border border-gray-200 px-3 py-1.5 text-xs text-gray-700 hover:border-brand-500 hover:text-brand-700 disabled:opacity-50"
        >
          <Plus className="h-3.5 w-3.5" />新增方案
        </button>
      </div>

      {pending.length ? (
        <PendingPanel
          items={pending}
          resolvingItem={resolvingItem}
          onResolve={resolvePending}
          onModify={modifyPending}
        />
      ) : null}

      {loading ? <Loading label="正在读取方案" /> : null}

      {scenarios.map((scenario, index) => (
        <ScenarioBlock
          key={scenario.id}
          scenario={scenario}
          index={index}
          framed={multi}
          indicatorByColumn={indicatorByColumn}
          sourceByField={sourceByField}
          busy={busy}
          onShowEvidence={setOpenEvidence}
          onSave={(patch) => saveScenario(scenario, patch)}
          onCopy={() => void copyScenario(scenario)}
          onDelete={() => void deleteScenario(scenario)}
        />
      ))}

      {!loading && !scenarios.length ? (
        <div className="border border-dashed border-gray-200 px-4 py-5 text-sm text-gray-500">
          这条需求还没有任何方案。方案是门槛唯一的住处 —— 点「新增方案」开始填，
          或者重新发起一次解析让它从原始材料里切出来。
        </div>
      ) : null}

      {openEvidence ? <EvidencePopover source={openEvidence} onClose={() => setOpenEvidence(null)} /> : null}
    </div>
  );
}

function ScenarioBlock({
  scenario,
  index,
  framed,
  indicatorByColumn,
  sourceByField,
  busy,
  onShowEvidence,
  onSave,
  onCopy,
  onDelete,
}: {
  scenario: BuyerIntentScenario;
  index: number;
  framed: boolean;
  indicatorByColumn: Map<string, IndicatorMeta>;
  sourceByField: Map<string, FieldValueSource>;
  busy: boolean;
  onShowEvidence: (source: FieldValueSource) => void;
  onSave: (patch: Record<string, unknown>) => Promise<void>;
  onCopy: () => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const [summaryHintDismissed, setSummaryHintDismissed] = useState(false);

  const fields = scenario as unknown as Record<string, unknown>;
  // 摘要里通常写着「收入 5-50 亿」这类数字，顾问改了门槛格子之后它就过期了。
  // 只做**弱提示**：摘要允许手改，系统不替他改，也不拦着他保存。
  const summaryStale = useMemo(() => {
    const summary = String(fields.scenario_summary || '');
    if (!summary) return false;
    const summaryUpdated = Date.parse(scenario.updated_at);
    void summaryUpdated;
    return THRESHOLD_LAYOUT.flat().filter(Boolean).some((column) => {
      const source = sourceByField.get(column);
      return source?.source_type === 'manual';
    });
  }, [fields.scenario_summary, scenario.updated_at, sourceByField]);

  const commit = useCallback(async (column: string, value: unknown) => {
    setSaving(true);
    try {
      await onSave({ [column]: value });
      setEditing(null);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }, [onSave]);

  const cell = (column: string) => {
    if (!column) return <div key="spacer" />;
    const indicator = indicatorByColumn.get(column);
    if (!indicator) return <div key={column} />;
    const value = fields[column];
    const source = sourceByField.get(column);
    const isEditing = editing === column;
    return (
      <div key={column} className="flex min-w-0 items-start gap-2 py-1">
        <span className="w-24 shrink-0 pt-1 text-xs text-gray-500">{indicator.label}</span>
        {isEditing ? (
          <div className="min-w-0 flex-1 space-y-2">
            <FieldEditor indicator={indicator} value={draft} onValue={setDraft} />
            <div className="flex gap-2">
              <button type="button" disabled={saving} onClick={() => void commit(column, draft)} className="inline-flex items-center gap-1 bg-brand-600 px-2.5 py-1 text-xs text-white disabled:opacity-50">{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}保存</button>
              <button type="button" disabled={saving} onClick={() => setEditing(null)} className="inline-flex items-center gap-1 border border-gray-200 px-2.5 py-1 text-xs text-gray-600"><X className="h-3.5 w-3.5" />取消</button>
            </div>
          </div>
        ) : (
          <>
            <span className={`min-w-0 flex-1 whitespace-pre-wrap pt-1 text-sm ${hasValue(value) ? 'text-gray-800' : 'text-gray-300'}`}>
              {hasValue(value) ? formatFieldValue(indicator, value) : '-'}
            </span>
            {source && hasReadableEvidence(source) ? (
              <IconButton title={sourceDetailText(source)} onClick={() => onShowEvidence(source)}><Search className="h-3.5 w-3.5" /></IconButton>
            ) : null}
            <IconButton title={`编辑${indicator.label}`} onClick={() => { setDraft(value ?? null); setEditing(column); }}><Pencil className="h-3.5 w-3.5" /></IconButton>
          </>
        )}
      </div>
    );
  };

  const body = (
    <div className="space-y-3">
      {/* 要买什么 —— 摘要就是这个方案的标题 */}
      <div className="space-y-1">
        {cell('scenario_summary')}
        {summaryStale && !summaryHintDismissed ? (
          <div className="ml-24 flex items-center gap-2 text-[11px] text-amber-700">
            <span>门槛改过，摘要可能已经不一致。</span>
            <button type="button" onClick={() => setSummaryHintDismissed(true)} className="underline">知道了</button>
          </div>
        ) : null}
        {cell('business_tags_json')}
        {cell('excluded_business_text')}
      </div>

      {/* 门槛 */}
      <div className="border-t border-gray-100 pt-3">
        <p className="mb-1.5 text-[11px] font-semibold text-gray-400">
          门槛 —— 这些会进初筛。<span className="text-gray-500">留空 = 不筛，不是漏填。</span>
          「优先大湾区」这类偏好写进下面的「其他要求」，填进这里会把外地的好标的直接筛掉。
        </p>
        <div className="grid gap-x-6 lg:grid-cols-2">
          {THRESHOLD_LAYOUT.map((row) => row.map((column) => cell(column)))}
        </div>
      </div>

      {/* 其他要求 */}
      <div className="border-t border-gray-100 pt-3">
        <p className="mb-1.5 text-[11px] font-semibold text-gray-400">其他要求 —— 不进初筛，交给深度评估</p>
        {cell('other_requirements_text')}
      </div>
    </div>
  );

  if (!framed) return <section className="border border-gray-200 bg-white p-4">{body}</section>;

  return (
    <section className="border border-gray-200 bg-white">
      <div className="flex items-center justify-between border-b border-gray-100 bg-gray-50 px-4 py-2">
        <span className="text-xs font-semibold text-gray-600">方案 {index + 1}</span>
        <div className="flex items-center gap-1">
          <IconButton title="复制这个方案" onClick={onCopy}><Copy className="h-3.5 w-3.5" /></IconButton>
          <IconButton title="删除这个方案" onClick={onDelete}><Trash2 className="h-3.5 w-3.5" /></IconButton>
        </div>
      </div>
      <div className={`p-4 ${busy ? 'opacity-60' : ''}`}>{body}</div>
    </section>
  );
}

function PendingPanel({ items, resolvingItem, onResolve, onModify }: {
  items: PendingItem[];
  resolvingItem: string | null;
  onResolve: (item: PendingItem, action: 'apply' | 'discard') => void | Promise<void>;
  onModify: (item: PendingItem) => void;
}) {
  return (
    <div className="space-y-2 border border-amber-200 bg-amber-50 p-3">
      {items.map((item) => {
        const key = confirmationKey(item);
        return (
          <div key={key} className="border border-amber-200 bg-white px-3 py-2 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-gray-700">{item.scopeLabel} · {item.field}</span>
              <span className="text-gray-500">{item.reason}</span>
            </div>
            {item.evidence ? <p className="mt-1 whitespace-pre-wrap text-gray-500">原文：{item.evidence}</p> : null}
            {item.proposed_value !== undefined ? (
              <p className="mt-1 text-gray-700">建议值：{displayUnknown(item.proposed_value)}</p>
            ) : null}
            <div className="mt-2 flex flex-wrap gap-2">
              {item.proposed_value !== undefined ? <button type="button" disabled={resolvingItem === key} onClick={() => void onResolve(item, 'apply')} className="border border-amber-300 bg-white px-2.5 py-1 text-xs text-amber-800 disabled:opacity-50">采纳建议值</button> : null}
              {item.proposed_value !== undefined ? <button type="button" disabled={resolvingItem === key} onClick={() => onModify(item)} className="border border-gray-200 bg-white px-2.5 py-1 text-xs text-gray-600 disabled:opacity-50">修改并采纳</button> : null}
              <button type="button" disabled={resolvingItem === key} onClick={() => void onResolve(item, 'discard')} className="border border-gray-200 bg-white px-2.5 py-1 text-xs text-gray-600 disabled:opacity-50">不设置该条件</button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function FieldEditor({ indicator, value, onValue }: {
  indicator: IndicatorMeta;
  value: unknown;
  onValue: (value: unknown) => void;
}) {
  if (indicator.editor === 'region_multi') return <RegionConstraintsEditor value={regionArray(value)} onChange={onValue} />;
  if (indicator.editor === 'multi_enum') return <CheckboxOptions value={stringArray(value)} options={indicator.enum_options} onChange={onValue} />;
  if (indicator.editor === 'tags') return <input className="input" value={stringArray(value).join('、')} onChange={(event) => onValue(splitTerms(event.target.value))} placeholder="多个值用顿号、逗号或换行分隔" />;
  if (indicator.kind === 'yuan' || indicator.kind === 'ratio') return <input className="input" type="number" value={stringValue(value)} onChange={(event) => onValue(event.target.value === '' ? null : event.target.value)} />;
  if (indicator.editor === 'textarea') return <textarea className="input min-h-24 resize-y" value={stringValue(value)} onChange={(event) => onValue(event.target.value)} />;
  return <input className="input" value={stringValue(value)} onChange={(event) => onValue(event.target.value)} />;
}

/** 省市区三级，逐级独立生效：只填省 = 全省命中。
 *
 * 0901 删掉了每条地区上那个「必须 / 优先 / 排除」下拉。它写的 `effect` 键
 * 从 022 起会被 `normalize_buyer_regions` 静默吃掉 —— 顾问选「排除」得到的
 * 仍然是可接受地区，跟他选的正好相反，而且不报错。 */
export function RegionConstraintsEditor({ value, onChange }: { value: BuyerRegionConstraint[]; onChange: (value: BuyerRegionConstraint[]) => void }) {
  return (
    <div className="space-y-2 border border-gray-200 bg-gray-50 p-3">
      {value.map((item, index) => (
        <div key={`${item.province}-${item.city || ''}-${item.district || ''}-${index}`} className="grid min-w-0 gap-2 border-b border-gray-200 pb-2 lg:grid-cols-[minmax(0,1fr)_auto]">
          <AdministrativeAreaPicker value={item} onChange={(area) => onChange(value.map((entry, itemIndex) => (itemIndex === index ? area : entry)))} />
          <button type="button" onClick={() => onChange(value.filter((_, itemIndex) => itemIndex !== index))} className="text-xs text-red-600">移除</button>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...value, { province: '' }])} className="inline-flex items-center gap-1 text-xs text-brand-700"><Plus className="h-3.5 w-3.5" />添加地区</button>
      <p className="text-[11px] text-gray-400">这里是**硬要求**：填了就会把其他地区的标的筛掉。「优先某地」写进「其他要求」。“全国”不生成地区条件；长三角、大湾区等由系统在解析阶段展开为标准省份。</p>
    </div>
  );
}

function EvidencePopover({ source, onClose }: { source: FieldValueSource; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <div className="max-h-[70vh] w-full max-w-xl overflow-y-auto border border-gray-200 bg-white p-4" onClick={(event) => event.stopPropagation()}>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-medium text-gray-700">{source.field_path} 的来源</span>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-700"><X className="h-4 w-4" /></button>
        </div>
        <p className="text-xs text-gray-500">{sourceDetailText(source)}</p>
        {source.evidence_span ? (
          <pre className="mt-2 whitespace-pre-wrap bg-gray-50 p-3 text-xs text-gray-700">{JSON.stringify(source.evidence_span, null, 2)}</pre>
        ) : null}
      </div>
    </div>
  );
}

function CheckboxOptions({ value, options, onChange }: { value: string[]; options: Array<{ value: string; label: string }>; onChange: (value: string[]) => void }) {
  return <div className="flex min-h-9 flex-wrap gap-2 border border-gray-200 bg-white p-2">{options.map((option) => <label key={option.value} className="inline-flex items-center gap-1 text-xs text-gray-700"><input type="checkbox" checked={value.includes(option.value)} onChange={() => onChange(value.includes(option.value) ? value.filter((item) => item !== option.value) : [...value, option.value])} />{option.label}</label>)}</div>;
}

function formatFieldValue(indicator: IndicatorMeta, value: unknown): string {
  // 直辖市的省与市同名，直接拼会变成「北京市北京市」。
  if (indicator.editor === 'region_multi') return regionArray(value).map((item) => [...new Set([item.province, item.city, item.district].filter(Boolean))].join('')).join('、');
  if (indicator.kind === 'yuan') return moneyText(value);
  if (indicator.kind === 'enum') return indicator.enum_options.find((option) => option.value === value)?.label || String(value);
  if (Array.isArray(value)) return value.map((item) => indicator.enum_options.find((option) => option.value === item)?.label || displayUnknown(item)).join('、');
  return String(value);
}

function mergeProposedValue(current: unknown, proposed: unknown): unknown {
  if (!Array.isArray(current)) return proposed;
  const additions = Array.isArray(proposed) ? proposed : [proposed];
  const seen = new Set(current.map((item) => JSON.stringify(item)));
  return [...current, ...additions.filter((item) => { const key = JSON.stringify(item); if (seen.has(key)) return false; seen.add(key); return true; })];
}

function regionArray(value: unknown): BuyerRegionConstraint[] { return Array.isArray(value) ? value.filter((item): item is BuyerRegionConstraint => Boolean(item) && typeof item === 'object' && 'province' in item) : []; }
function stringArray(value: unknown): string[] { return Array.isArray(value) ? value.map(String).filter(Boolean) : []; }
function stringValue(value: unknown, fallback = ''): string { return value === null || value === undefined || value === '' ? fallback : String(value); }
function splitTerms(value: string): string[] { return [...new Set(value.split(/[、，,\n]/).map((item) => item.trim()).filter(Boolean))]; }
function hasValue(value: unknown): boolean { return value !== null && value !== undefined && value !== '' && value !== 'unknown' && (!Array.isArray(value) || value.length > 0); }
function moneyText(value: unknown): string { const number = Number(value); if (!Number.isFinite(number)) return String(value); if (Math.abs(number) < 10_000) return `${number.toFixed(0)}元`; if (Math.abs(number) < 100_000_000) return `${(number / 10_000).toFixed(0)}万`; return `${(number / 100_000_000).toFixed(1)}亿`; }
function displayUnknown(value: unknown): string { return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value); }
function confirmationKey(item: PendingItem): string { return `${item.scopeLabel}:${item.item_key || item.field}:${item.uncertain_part || ''}`; }
function sameConfirmation(left: BuyerIntentConfirmationItem, right: BuyerIntentConfirmationItem): boolean { if (left.item_key || right.item_key) return left.item_key === right.item_key; return left.field === right.field && (left.evidence || '') === (right.evidence || '') && left.reason === right.reason; }
function StateBadge({ tone, text }: { tone: 'amber' | 'green' | 'gray'; text: string }) { const style = tone === 'amber' ? 'bg-amber-50 text-amber-700' : tone === 'green' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600'; return <span className={`px-2 py-0.5 text-xs font-medium ${style}`}>{text}</span>; }
function IconButton({ title, onClick, children }: { title: string; onClick: () => void; children: ReactNode }) { return <button type="button" title={title} onClick={onClick} className="p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700">{children}</button>; }
function Loading({ label }: { label: string }) { return <div className="flex items-center justify-center border border-gray-100 py-8 text-sm text-gray-400"><Loader2 className="mr-2 h-4 w-4 animate-spin" />{label}</div>; }
