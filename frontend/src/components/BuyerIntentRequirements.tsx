import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Dispatch, ReactNode, SetStateAction } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  Copy,
  Loader2,
  Pencil,
  Plus,
  Save,
  Trash2,
  X,
} from 'lucide-react';
import { buyerIntents, meta } from '../lib/api';
import type {
  BuyerIntent,
  BuyerIntentConfirmationItem,
  BuyerIntentParseStatus,
  BuyerIntentScenario,
  BuyerIntentScenarioWrite,
  BuyerIntentUpdate,
  IndustryOptionsResponse,
} from '../types/api';
import { valueLabel } from '../lib/fieldLabels';

type RuleRole = 'hard' | 'soft' | 'deep' | 'pending';

interface SharedDraft {
  intent_summary: string;
  industries_json: string[];
  industry_l2_json: string[];
  excluded_industries_json: string[];
  industry_focus_tags_json: string;
  region_scope_summary: string;
  min_revenue_yuan: string;
  min_net_profit_yuan: string;
  max_pe: string;
  max_valuation_yuan: string;
  requires_control: string;
  requires_consolidation: string;
  preferred_listed_status: string;
  priority_summary: string;
  preference_summary: string;
  negative_summary: string;
}

const SCENARIO_FIELDS = [
  'min_revenue_yuan',
  'min_net_profit_yuan',
  'max_pe',
  'max_valuation_yuan',
  'min_market_cap_yuan',
  'max_market_cap_yuan',
  'requires_control',
  'requires_consolidation',
  'preferred_listed_status',
] as const;

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
  const [taxonomy, setTaxonomy] = useState<IndustryOptionsResponse>({ l1: [], l2: [] });
  const [loadingScenarios, setLoadingScenarios] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [resolvingItem, setResolvingItem] = useState<string | null>(null);
  const [draft, setDraft] = useState<SharedDraft>(() => sharedDraft(intent));

  const loadScenarios = useCallback(async () => {
    setLoadingScenarios(true);
    try {
      setScenarios(await buyerIntents.scenarios(intent.id));
    } finally {
      setLoadingScenarios(false);
    }
  }, [intent.id]);

  useEffect(() => { void loadScenarios(); }, [loadScenarios]);
  useEffect(() => { setDraft(sharedDraft(intent)); }, [intent]);
  useEffect(() => { meta.industryOptions().then(setTaxonomy).catch(() => {}); }, []);

  const allPending = useMemo<Array<BuyerIntentConfirmationItem & { scope: string; scenario?: BuyerIntentScenario }>>(
    () => [
      ...(intent.needs_confirmation_json || []).map((item) => ({ ...item, scope: '公共条件' })),
      ...scenarios.flatMap((scenario) =>
        (scenario.needs_confirmation_json || []).map((item) => ({ ...item, scope: scenario.label, scenario })),
      ),
    ],
    [intent.needs_confirmation_json, scenarios],
  );

  const saveShared = async () => {
    setSaving(true);
    try {
      const payload: BuyerIntentUpdate = {
        intent_summary: nullIfEmpty(draft.intent_summary),
        industries_json: draft.industries_json,
        industry_l2_json: draft.industry_l2_json,
        excluded_industries_json: draft.excluded_industries_json,
        industry_focus_tags_json: splitTerms(draft.industry_focus_tags_json),
        region_scope_summary: nullIfEmpty(draft.region_scope_summary),
        min_revenue_yuan: nullableNumber(draft.min_revenue_yuan),
        min_net_profit_yuan: nullableNumber(draft.min_net_profit_yuan),
        max_pe: nullableNumber(draft.max_pe),
        max_valuation_yuan: nullableNumber(draft.max_valuation_yuan),
        requires_control: draft.requires_control,
        requires_consolidation: draft.requires_consolidation,
        preferred_listed_status: draft.preferred_listed_status,
        priority_summary: nullIfEmpty(draft.priority_summary),
        preference_summary: nullIfEmpty(draft.preference_summary),
        negative_summary: nullIfEmpty(draft.negative_summary),
      };
      await buyerIntents.update(intent.id, payload);
      setEditing(false);
      await onRefresh?.();
    } catch (error) {
      alert(error instanceof Error ? error.message : '保存需求失败');
    } finally {
      setSaving(false);
    }
  };

  const addScenario = async () => {
    const created = await buyerIntents.createScenario(intent.id, {
      label: `方案 ${String.fromCharCode(65 + scenarios.length)}`,
      sort_order: scenarios.length,
      active: true,
      fields_json: {},
    });
    setScenarios((current) => [...current, created]);
  };

  const copyScenario = async (scenario: BuyerIntentScenario) => {
    const created = await buyerIntents.createScenario(intent.id, {
      label: `${scenario.label}（复制）`,
      sort_order: scenarios.length,
      active: scenario.active,
      fields_json: scenario.fields_json,
      needs_confirmation_json: scenario.needs_confirmation_json,
    });
    setScenarios((current) => [...current, created]);
  };

  const deleteScenario = async (scenario: BuyerIntentScenario) => {
    if (!window.confirm(`确认删除“${scenario.label}”？`)) return;
    await buyerIntents.deleteScenario(intent.id, scenario.id);
    setScenarios((current) => current.filter((item) => item.id !== scenario.id));
  };

  const completeReview = async () => {
    if (allPending.length && !window.confirm('确认已人工核对这些事项并清除“需要确认”状态？')) return;
    setReviewing(true);
    try {
      await buyerIntents.review(intent.id, allPending.length > 0);
      await Promise.all([loadScenarios(), onRefresh?.()]);
    } catch (error) {
      alert(error instanceof Error ? error.message : '完成复核失败');
    } finally {
      setReviewing(false);
    }
  };

  const resolvePending = async (
    item: BuyerIntentConfirmationItem & { scope: string; scenario?: BuyerIntentScenario },
    applyProposedValue: boolean,
  ) => {
    const key = `${item.scope}:${item.field}`;
    setResolvingItem(key);
    try {
      if (item.scenario) {
        const nextPending = item.scenario.needs_confirmation_json.filter((entry) => !sameConfirmation(entry, item));
        const nextFields = applyProposedValue
          ? { ...item.scenario.fields_json, [item.field]: item.proposed_value }
          : item.scenario.fields_json;
        const updated = await buyerIntents.updateScenario(intent.id, item.scenario.id, {
          label: item.scenario.label,
          sort_order: item.scenario.sort_order,
          active: item.scenario.active,
          fields_json: nextFields,
          needs_confirmation_json: nextPending,
        });
        setScenarios((current) => current.map((scenario) => scenario.id === updated.id ? updated : scenario));
      } else {
        if (applyProposedValue) {
          await buyerIntents.update(intent.id, { [item.field]: item.proposed_value } as BuyerIntentUpdate);
        } else {
          await buyerIntents.update(intent.id, {
            needs_confirmation_json: (intent.needs_confirmation_json || []).filter((entry) => !sameConfirmation(entry, item)),
          });
        }
        await onRefresh?.();
      }
    } catch (error) {
      alert(error instanceof Error ? error.message : '处理待确认事项失败');
    } finally {
      setResolvingItem(null);
    }
  };

  const failedJob = parseStatus?.latest_job?.status === 'failed' ? parseStatus.latest_job : null;

  return (
    <div className="space-y-6">
      {failedJob ? (
        <div className="flex items-start gap-2 border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div><p className="font-medium">最近一次解析失败</p><p className="mt-1 text-xs">{failedJob.error_message || '请重新发起解析。'}</p></div>
        </div>
      ) : null}

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-gray-500">需求摘要</p>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-gray-800">{intent.intent_summary || '暂无需求摘要'}</p>
        </div>
        <div className="flex items-center gap-2">
          {allPending.length ? <StateBadge tone="amber" text={`${allPending.length} 项需要确认`} /> : null}
          {intent.reviewed_at ? <StateBadge tone="green" text="已人工复核" /> : <StateBadge tone="gray" text="尚未人工复核" />}
          <button type="button" onClick={() => setEditing((value) => !value)} className="inline-flex items-center gap-1 border border-gray-200 px-3 py-1.5 text-xs text-gray-700 hover:border-brand-500 hover:text-brand-700">
            {editing ? <X className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}{editing ? '取消编辑' : '编辑公共条件'}
          </button>
        </div>
      </div>

      {editing ? (
        <SharedEditor draft={draft} setDraft={setDraft} taxonomy={taxonomy} saving={saving} onSave={saveShared} />
      ) : (
        <section className="border border-gray-200">
          <SectionHeader title="公共条件" subtitle="与下面任一启用方案共同生效" />
          <div className="divide-y divide-gray-100 px-4">
            {sharedConditionRows(intent).map((row) => <ConditionLine key={row.label} {...row} />)}
          </div>
        </section>
      )}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div><p className="text-xs font-semibold text-gray-500">需求方案</p><p className="mt-1 text-xs text-gray-400">匹配逻辑：公共条件 AND（任一启用方案）</p></div>
          <button type="button" onClick={() => void addScenario()} className="inline-flex items-center gap-1 border border-gray-200 px-3 py-1.5 text-xs text-gray-700 hover:border-brand-500 hover:text-brand-700"><Plus className="h-3.5 w-3.5" />新增方案</button>
        </div>
        {loadingScenarios ? <Loading /> : scenarios.length ? scenarios.map((scenario) => (
          <ScenarioCard
            key={scenario.id}
            intentId={intent.id}
            scenario={scenario}
            taxonomy={taxonomy}
            onSaved={(updated) => setScenarios((current) => current.map((item) => item.id === updated.id ? updated : item))}
            onCopy={() => void copyScenario(scenario)}
            onDelete={() => void deleteScenario(scenario)}
          />
        )) : (
          <div className="border border-dashed border-gray-200 px-4 py-5 text-sm text-gray-500">未设置显式方案，当前需求按一套公共条件进行匹配。</div>
        )}
      </section>

      <section className={`border ${allPending.length ? 'border-amber-200 bg-amber-50/40' : 'border-gray-200'}`}>
        <div className="flex items-center justify-between border-b border-inherit px-4 py-3">
          <div><p className="text-sm font-semibold text-gray-900">待确认事项</p><p className="mt-0.5 text-xs text-gray-500">确认前不参加初筛和软排序，但会进入 AI 深评。</p></div>
          <button type="button" onClick={() => void completeReview()} disabled={reviewing} className="inline-flex items-center gap-1 bg-brand-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">
            {reviewing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}{allPending.length ? '完成复核' : '标记已复核'}
          </button>
        </div>
        <div className="divide-y divide-amber-100 px-4">
          {allPending.length ? allPending.map((item, index) => (
            <div key={`${item.scope}-${item.field}-${index}`} className="py-3 text-sm">
              <div className="flex flex-wrap items-center gap-2"><RoleBadge role="pending" /><span className="font-medium text-gray-900">{item.scope} · {fieldLabel(item.field)}</span></div>
              <p className="mt-1 text-gray-700">{item.reason}</p>
              {item.proposed_value !== undefined ? <p className="mt-1 text-xs text-gray-500">AI 建议值：{displayValue(item.proposed_value)}</p> : null}
              {item.evidence ? <p className="mt-1 text-xs text-gray-500">原文：{item.evidence}</p> : null}
              <div className="mt-2 flex flex-wrap gap-2">
                {item.proposed_value !== undefined ? <button type="button" disabled={resolvingItem === `${item.scope}:${item.field}`} onClick={() => void resolvePending(item, true)} className="border border-amber-300 bg-white px-2.5 py-1 text-xs text-amber-800 disabled:opacity-50">采纳建议值</button> : null}
                <button type="button" disabled={resolvingItem === `${item.scope}:${item.field}`} onClick={() => void resolvePending(item, false)} className="border border-gray-200 bg-white px-2.5 py-1 text-xs text-gray-600 disabled:opacity-50">已核对，不设置该条件</button>
              </div>
            </div>
          )) : <p className="py-4 text-sm text-gray-500">暂无待确认事项。</p>}
        </div>
      </section>

      <section>
        <p className="mb-2 text-xs font-semibold text-gray-500">原始需求材料</p>
        <p className="max-h-72 overflow-y-auto whitespace-pre-wrap bg-gray-50 px-4 py-3 text-sm leading-6 text-gray-700">{intent.raw_requirement_text || '暂无原始需求材料'}</p>
      </section>
    </div>
  );
}

function SharedEditor({ draft, setDraft, taxonomy, saving, onSave }: {
  draft: SharedDraft;
  setDraft: Dispatch<SetStateAction<SharedDraft>>;
  taxonomy: IndustryOptionsResponse;
  saving: boolean;
  onSave: () => void;
}) {
  const set = <K extends keyof SharedDraft>(key: K, value: SharedDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  return (
    <section className="space-y-4 border border-brand-200 bg-brand-50/20 p-4">
      <TextArea label="需求摘要" value={draft.intent_summary} onChange={(value) => set('intent_summary', value)} />
      <div className="grid gap-4 lg:grid-cols-3">
        <MultiSelect label="一级目标行业（硬筛）" values={draft.industries_json} options={taxonomy.l1.map((item) => item.term)} onChange={(value) => set('industries_json', value)} />
        <MultiSelect label="二级关注行业（软排）" values={draft.industry_l2_json} options={taxonomy.l2.map((item) => item.term)} onChange={(value) => set('industry_l2_json', value)} />
        <MultiSelect label="排除行业（硬排除）" values={draft.excluded_industries_json} options={[...taxonomy.l1, ...taxonomy.l2].map((item) => item.term)} onChange={(value) => set('excluded_industries_json', value)} />
      </div>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Input label="地域范围（软排）" value={draft.region_scope_summary} onChange={(value) => set('region_scope_summary', value)} />
        <Input label="最低营收（元）" type="number" value={draft.min_revenue_yuan} onChange={(value) => set('min_revenue_yuan', value)} />
        <Input label="最低净利润（元）" type="number" value={draft.min_net_profit_yuan} onChange={(value) => set('min_net_profit_yuan', value)} />
        <Input label="PE 上限" type="number" value={draft.max_pe} onChange={(value) => set('max_pe', value)} />
        <Input label="估值上限（元）" type="number" value={draft.max_valuation_yuan} onChange={(value) => set('max_valuation_yuan', value)} />
        <EnumSelect label="控股要求" value={draft.requires_control} options={YES_NO_OPTIONS} onChange={(value) => set('requires_control', value)} />
        <EnumSelect label="并表要求" value={draft.requires_consolidation} options={YES_NO_OPTIONS} onChange={(value) => set('requires_consolidation', value)} />
        <EnumSelect label="上市状态偏好" value={draft.preferred_listed_status} options={LISTED_OPTIONS} onChange={(value) => set('preferred_listed_status', value)} />
      </div>
      <Input label="字典外细分方向（以、或逗号分隔，仅深评）" value={draft.industry_focus_tags_json} onChange={(value) => set('industry_focus_tags_json', value)} />
      <div className="grid gap-4 md:grid-cols-3">
        <TextArea label="优先条件" value={draft.priority_summary} onChange={(value) => set('priority_summary', value)} />
        <TextArea label="其他偏好" value={draft.preference_summary} onChange={(value) => set('preference_summary', value)} />
        <TextArea label="排除与风险说明" value={draft.negative_summary} onChange={(value) => set('negative_summary', value)} />
      </div>
      <div className="flex justify-end"><button type="button" onClick={onSave} disabled={saving} className="inline-flex items-center gap-1 bg-brand-600 px-4 py-2 text-sm text-white disabled:opacity-50">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}保存公共条件</button></div>
    </section>
  );
}

function ScenarioCard({ intentId, scenario, taxonomy, onSaved, onCopy, onDelete }: {
  intentId: string;
  scenario: BuyerIntentScenario;
  taxonomy: IndustryOptionsResponse;
  onSaved: (scenario: BuyerIntentScenario) => void;
  onCopy: () => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [label, setLabel] = useState(scenario.label);
  const [sortOrder, setSortOrder] = useState(String(scenario.sort_order));
  const [active, setActive] = useState(scenario.active);
  const [fields, setFields] = useState<Record<string, unknown>>({ ...scenario.fields_json });

  useEffect(() => {
    setLabel(scenario.label); setSortOrder(String(scenario.sort_order)); setActive(scenario.active); setFields({ ...scenario.fields_json });
  }, [scenario]);

  const save = async () => {
    setSaving(true);
    try {
      const payload: BuyerIntentScenarioWrite = {
        label: label.trim() || scenario.label,
        sort_order: Number(sortOrder) || 0,
        active,
        fields_json: cleanScenarioFields(fields),
        needs_confirmation_json: scenario.needs_confirmation_json,
      };
      onSaved(await buyerIntents.updateScenario(intentId, scenario.id, payload));
      setEditing(false);
    } catch (error) {
      alert(error instanceof Error ? error.message : '保存方案失败');
    } finally {
      setSaving(false);
    }
  };

  if (!editing) {
    const rows = scenarioConditionRows(scenario);
    return (
      <div className={`border ${scenario.active ? 'border-gray-200 bg-white' : 'border-gray-200 bg-gray-50 opacity-70'}`}>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-4 py-3">
          <div className="flex items-center gap-2"><p className="text-sm font-semibold text-gray-900">{scenario.label}</p><StateBadge tone={scenario.active ? 'green' : 'gray'} text={scenario.active ? '启用' : '停用'} /><span className="text-xs text-gray-400">排序 {scenario.sort_order}</span></div>
          <div className="flex items-center gap-1"><IconButton title="复制" onClick={onCopy}><Copy className="h-3.5 w-3.5" /></IconButton><IconButton title="编辑" onClick={() => setEditing(true)}><Pencil className="h-3.5 w-3.5" /></IconButton><IconButton title="删除" onClick={onDelete}><Trash2 className="h-3.5 w-3.5" /></IconButton></div>
        </div>
        <div className="divide-y divide-gray-100 px-4">{rows.length ? rows.map((row) => <ConditionLine key={row.label} {...row} />) : <p className="py-4 text-sm text-gray-500">该方案尚未设置差异化条件。</p>}</div>
        <p className="border-t border-gray-100 px-4 py-2 text-xs text-gray-400">有效画像 = 公共条件 + 本方案条件</p>
      </div>
    );
  }

  const setField = (key: string, value: unknown) => setFields((current) => ({ ...current, [key]: value }));
  return (
    <div className="space-y-4 border border-brand-200 bg-brand-50/20 p-4">
      <div className="grid gap-4 md:grid-cols-4">
        <Input label="方案名称" value={label} onChange={setLabel} />
        <Input label="排序" type="number" value={sortOrder} onChange={setSortOrder} />
        <EnumSelect label="状态" value={active ? 'active' : 'inactive'} options={[['active', '启用'], ['inactive', '停用']]} onChange={(value) => setActive(value === 'active')} />
        <MultiSelect label="一级行业（可覆盖公共条件）" values={stringArray(fields.industries_json)} options={taxonomy.l1.map((item) => item.term)} onChange={(value) => setField('industries_json', value)} />
      </div>
      <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-5">
        <EnumSelect label="上市状态" value={stringValue(fields.preferred_listed_status, 'unknown')} options={LISTED_OPTIONS} onChange={(value) => setField('preferred_listed_status', value)} />
        <Input label="最低营收（元）" type="number" value={stringValue(fields.min_revenue_yuan)} onChange={(value) => setField('min_revenue_yuan', value)} />
        <Input label="最低净利润（元）" type="number" value={stringValue(fields.min_net_profit_yuan)} onChange={(value) => setField('min_net_profit_yuan', value)} />
        <Input label="PE 上限" type="number" value={stringValue(fields.max_pe)} onChange={(value) => setField('max_pe', value)} />
        <Input label="估值上限（元）" type="number" value={stringValue(fields.max_valuation_yuan)} onChange={(value) => setField('max_valuation_yuan', value)} />
        <Input label="市值下限（元）" type="number" value={stringValue(fields.min_market_cap_yuan)} onChange={(value) => setField('min_market_cap_yuan', value)} />
        <Input label="市值上限（元）" type="number" value={stringValue(fields.max_market_cap_yuan)} onChange={(value) => setField('max_market_cap_yuan', value)} />
        <EnumSelect label="控股要求" value={stringValue(fields.requires_control, 'unknown')} options={YES_NO_OPTIONS} onChange={(value) => setField('requires_control', value)} />
        <EnumSelect label="并表要求" value={stringValue(fields.requires_consolidation, 'unknown')} options={YES_NO_OPTIONS} onChange={(value) => setField('requires_consolidation', value)} />
      </div>
      <div className="flex justify-end gap-2"><button type="button" onClick={() => setEditing(false)} className="border border-gray-200 px-3 py-1.5 text-xs text-gray-600">取消</button><button type="button" onClick={() => void save()} disabled={saving} className="inline-flex items-center gap-1 bg-brand-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}保存方案</button></div>
    </div>
  );
}

function sharedConditionRows(intent: BuyerIntent) {
  const rows = [
    row('一级目标行业', join(intent.industries_json), 'hard' as RuleRole),
    row('二级关注行业', join(intent.industry_l2_json), 'soft' as RuleRole),
    row('排除行业', join(intent.excluded_industries_json), 'hard' as RuleRole),
    row('地域范围', intent.region_scope_summary, 'soft' as RuleRole),
    row('最低营收', moneyText(intent.min_revenue_yuan), 'hard' as RuleRole),
    row('最低净利润', moneyText(intent.min_net_profit_yuan), 'hard' as RuleRole),
    row('PE 上限', intent.max_pe, 'hard' as RuleRole),
    row('估值上限', moneyText(intent.max_valuation_yuan), 'hard' as RuleRole),
    row('控股要求', valueLabel('yes_no_like', intent.requires_control), 'hard' as RuleRole),
    row('并表要求', valueLabel('yes_no_like', intent.requires_consolidation), 'hard' as RuleRole),
    row('上市状态偏好', intent.preferred_listed_status ? valueLabel('preferred_listed_status', intent.preferred_listed_status) : null, 'soft' as RuleRole),
    row('细分关注方向', join(intent.industry_focus_tags_json), 'deep' as RuleRole),
    row('优先条件', intent.priority_summary, 'deep' as RuleRole),
    row('其他偏好', intent.preference_summary, 'deep' as RuleRole),
    row('风险与排除说明', intent.negative_summary, 'deep' as RuleRole),
  ];
  return rows.filter((item) => item.value && item.value !== '未知');
}

function scenarioConditionRows(scenario: BuyerIntentScenario) {
  const fields = scenario.fields_json;
  return [
    row('一级目标行业', join(stringArray(fields.industries_json)), 'hard' as RuleRole),
    row('上市状态', enumText(fields.preferred_listed_status, 'preferred_listed_status'), 'hard' as RuleRole),
    row('最低营收', moneyText(fields.min_revenue_yuan as string | number | null), 'hard' as RuleRole),
    row('最低净利润', moneyText(fields.min_net_profit_yuan as string | number | null), 'hard' as RuleRole),
    row('PE 上限', fields.max_pe as string | number | null, 'hard' as RuleRole),
    row('估值上限', moneyText(fields.max_valuation_yuan as string | number | null), 'hard' as RuleRole),
    row('市值下限', moneyText(fields.min_market_cap_yuan as string | number | null), 'hard' as RuleRole),
    row('市值上限', moneyText(fields.max_market_cap_yuan as string | number | null), 'hard' as RuleRole),
    row('控股要求', enumText(fields.requires_control, 'yes_no_like'), 'hard' as RuleRole),
    row('并表要求', enumText(fields.requires_consolidation, 'yes_no_like'), 'hard' as RuleRole),
  ].filter((item) => item.value && item.value !== '未知');
}

function ConditionLine({ label, value, role }: { label: string; value: string | number | null | undefined; role: RuleRole }) {
  return <div className="flex items-start gap-3 py-2.5"><RoleBadge role={role} /><span className="w-28 shrink-0 text-xs text-gray-500">{label}</span><span className="min-w-0 whitespace-pre-wrap text-sm text-gray-800">{value || '-'}</span></div>;
}

function RoleBadge({ role }: { role: RuleRole }) {
  const styles: Record<RuleRole, string> = { hard: 'bg-red-50 text-red-700', soft: 'bg-blue-50 text-blue-700', deep: 'bg-violet-50 text-violet-700', pending: 'bg-amber-100 text-amber-800' };
  const labels: Record<RuleRole, string> = { hard: '硬筛', soft: '软排', deep: '深评', pending: '需要确认' };
  return <span className={`w-16 shrink-0 px-1.5 py-0.5 text-center text-[11px] font-medium ${styles[role]}`}>{labels[role]}</span>;
}

function SectionHeader({ title, subtitle }: { title: string; subtitle: string }) { return <div className="border-b border-gray-100 px-4 py-3"><p className="text-sm font-semibold text-gray-900">{title}</p><p className="mt-0.5 text-xs text-gray-400">{subtitle}</p></div>; }
function StateBadge({ tone, text }: { tone: 'amber' | 'green' | 'gray'; text: string }) { const style = tone === 'amber' ? 'bg-amber-50 text-amber-700' : tone === 'green' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600'; return <span className={`px-2 py-0.5 text-xs font-medium ${style}`}>{text}</span>; }
function IconButton({ title, onClick, children }: { title: string; onClick: () => void; children: ReactNode }) { return <button type="button" title={title} onClick={onClick} className="p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700">{children}</button>; }
function Loading() { return <div className="flex items-center justify-center border border-gray-100 py-8 text-sm text-gray-400"><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在读取方案</div>; }

function Input({ label, value, onChange, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; type?: string }) { return <label className="block"><span className="mb-1 block text-xs font-medium text-gray-600">{label}</span><input type={type} className="input" value={value} onChange={(event) => onChange(event.target.value)} /></label>; }
function TextArea({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label className="block"><span className="mb-1 block text-xs font-medium text-gray-600">{label}</span><textarea className="input min-h-20 resize-y" value={value} onChange={(event) => onChange(event.target.value)} /></label>; }
function EnumSelect({ label, value, options, onChange }: { label: string; value: string; options: string[][]; onChange: (value: string) => void }) { return <label className="block"><span className="mb-1 block text-xs font-medium text-gray-600">{label}</span><select className="input" value={value} onChange={(event) => onChange(event.target.value)}>{options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label>; }
function MultiSelect({ label, values, options, onChange }: { label: string; values: string[]; options: string[]; onChange: (value: string[]) => void }) { return <label className="block"><span className="mb-1 block text-xs font-medium text-gray-600">{label}</span><select multiple className="input min-h-28" value={values} onChange={(event) => onChange(Array.from(event.currentTarget.selectedOptions, (option) => option.value))}>{options.map((option) => <option key={option} value={option}>{option}</option>)}</select><span className="mt-1 block text-[11px] text-gray-400">按 Ctrl / Command 可多选</span></label>; }

const YES_NO_OPTIONS = [['unknown', '未要求'], ['yes', '是'], ['no', '否'], ['likely', '倾向是']];
const LISTED_OPTIONS = [['unknown', '未要求'], ['any', '均可'], ['listed', '已上市'], ['unlisted', '未上市'], ['preparing_listing', '准备上市'], ['pre_ipo', 'Pre-IPO']];

function sharedDraft(intent: BuyerIntent): SharedDraft { return {
  intent_summary: intent.intent_summary || '', industries_json: intent.industries_json || [], industry_l2_json: intent.industry_l2_json || [], excluded_industries_json: intent.excluded_industries_json || [], industry_focus_tags_json: (intent.industry_focus_tags_json || []).join('、'), region_scope_summary: intent.region_scope_summary || '', min_revenue_yuan: stringValue(intent.min_revenue_yuan), min_net_profit_yuan: stringValue(intent.min_net_profit_yuan), max_pe: stringValue(intent.max_pe), max_valuation_yuan: stringValue(intent.max_valuation_yuan), requires_control: intent.requires_control || 'unknown', requires_consolidation: intent.requires_consolidation || 'unknown', preferred_listed_status: intent.preferred_listed_status || 'unknown', priority_summary: intent.priority_summary || '', preference_summary: intent.preference_summary || '', negative_summary: intent.negative_summary || '',
}; }
function cleanScenarioFields(fields: Record<string, unknown>) { const result: Record<string, unknown> = {}; for (const key of SCENARIO_FIELDS) { const value = fields[key]; if (value === '' || value === undefined || value === null || value === 'unknown') continue; result[key] = key.includes('_yuan') || key === 'max_pe' ? Number(value) : value; } const industries = stringArray(fields.industries_json); if (industries.length) result.industries_json = industries; return result; }
function row(label: string, value: string | number | null | undefined, role: RuleRole) { return { label, value, role }; }
function join(value: string[] | null | undefined) { return value?.filter(Boolean).join('、') || null; }
function stringArray(value: unknown): string[] { return Array.isArray(value) ? value.map(String).filter(Boolean) : []; }
function stringValue(value: unknown, fallback = ''): string { return value === null || value === undefined ? fallback : String(value); }
function nullableNumber(value: string): number | null { if (!value.trim()) return null; const parsed = Number(value); return Number.isFinite(parsed) ? parsed : null; }
function nullIfEmpty(value: string): string | null { return value.trim() || null; }
function splitTerms(value: string): string[] { return [...new Set(value.split(/[、,，;；\n]/).map((item) => item.trim()).filter(Boolean))]; }
function moneyText(value: string | number | null | undefined): string | null { if (value === null || value === undefined || value === '') return null; const number = Number(value); if (!Number.isFinite(number)) return String(value); if (Math.abs(number) < 10_000) return `${number.toFixed(0)}元`; if (Math.abs(number) < 100_000_000) return `${(number / 10_000).toFixed(0)}万`; return `${(number / 100_000_000).toFixed(1)}亿`; }
function enumText(value: unknown, field: string): string | null { return value ? valueLabel(field, String(value)) : null; }
function displayValue(value: unknown): string { return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value); }
function sameConfirmation(left: BuyerIntentConfirmationItem, right: BuyerIntentConfirmationItem): boolean { return left.field === right.field && (left.evidence || '') === (right.evidence || '') && left.reason === right.reason; }
function fieldLabel(field: string): string { const labels: Record<string, string> = { industries_json: '一级目标行业', industry_l2_json: '二级关注行业', min_revenue_yuan: '最低营收', min_net_profit_yuan: '最低净利润', max_pe: 'PE 上限', max_valuation_yuan: '估值上限', max_market_cap_yuan: '市值上限', requires_control: '控股要求', requires_consolidation: '并表要求', preferred_listed_status: '上市状态' }; return labels[field] || field; }
