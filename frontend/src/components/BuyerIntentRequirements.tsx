import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
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
import { buyerIntents, indicatorRegistry, meta } from '../lib/api';
import type {
  BuyerIntent,
  BuyerIntentConfirmationItem,
  BuyerIntentParseStatus,
  BuyerIntentScenario,
  BuyerIntentScenarioWrite,
  BuyerIntentUpdate,
  BuyerRegionConstraint,
  IndicatorGroupMeta,
  IndicatorMeta,
  IndicatorRegistryResponse,
  IndustryOptionsResponse,
} from '../types/api';
import IndustryPairsEditor, { type IndustryPairValue } from './IndustryPairsEditor';
import AdministrativeAreaPicker from './AdministrativeAreaPicker';

type ConditionEffect = 'required' | 'preferred' | 'deep_eval';
type PendingItem = BuyerIntentConfirmationItem & { scopeLabel: string; scenario?: BuyerIntentScenario };

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
  const [registry, setRegistry] = useState<IndicatorRegistryResponse | null>(null);
  const [loadingScenarios, setLoadingScenarios] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [resolvingItem, setResolvingItem] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>(() => intentDraft(intent));
  const [effects, setEffects] = useState<Record<string, ConditionEffect>>(intent.condition_effects_json || {});

  const loadScenarios = useCallback(async () => {
    setLoadingScenarios(true);
    try {
      setScenarios(await buyerIntents.scenarios(intent.id));
    } finally {
      setLoadingScenarios(false);
    }
  }, [intent.id]);

  useEffect(() => { void loadScenarios(); }, [loadScenarios]);
  useEffect(() => {
    setDraft(intentDraft(intent));
    setEffects(intent.condition_effects_json || {});
  }, [intent]);
  useEffect(() => {
    Promise.all([meta.industryOptions(), indicatorRegistry.list('buyer_intent')])
      .then(([industryData, registryData]) => { setTaxonomy(industryData); setRegistry(registryData); })
      .catch(() => {});
  }, []);

  const indicators = registry?.indicators || [];
  const allPending = useMemo<PendingItem[]>(
    () => [
      ...(intent.needs_confirmation_json || []).map((item) => ({ ...item, scopeLabel: '公共条件' })),
      ...scenarios.flatMap((scenario) =>
        (scenario.needs_confirmation_json || []).map((item) => ({ ...item, scopeLabel: scenario.label, scenario })),
      ),
    ],
    [intent.needs_confirmation_json, scenarios],
  );

  const saveShared = async () => {
    setSaving(true);
    try {
      const payload = {
        ...cleanFields(draft, indicators, false),
        condition_effects_json: effects,
      } as BuyerIntentUpdate;
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
      condition_effects_json: {},
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
      condition_effects_json: scenario.condition_effects_json,
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
    item: PendingItem,
    action: 'apply' | 'discard' | 'deep_eval',
    replacement?: unknown,
  ) => {
    const key = confirmationKey(item);
    setResolvingItem(key);
    try {
      const proposed = replacement === undefined ? item.proposed_value : replacement;
      if (item.scenario) {
        const scenario = item.scenario;
        const nextPending = scenario.needs_confirmation_json.filter((entry) => !sameConfirmation(entry, item));
        const currentValue = scenario.fields_json[item.field];
        const nextFields = action === 'discard' || proposed === undefined
          ? scenario.fields_json
          : { ...scenario.fields_json, [item.field]: mergeProposedValue(currentValue, proposed) };
        const nextEffects = action === 'deep_eval'
          ? { ...scenario.condition_effects_json, [item.field]: 'deep_eval' as const }
          : scenario.condition_effects_json;
        const updated = await buyerIntents.updateScenario(intent.id, scenario.id, {
          label: scenario.label,
          sort_order: scenario.sort_order,
          active: scenario.active,
          fields_json: nextFields,
          needs_confirmation_json: nextPending,
          condition_effects_json: nextEffects,
        });
        setScenarios((current) => current.map((entry) => entry.id === updated.id ? updated : entry));
      } else {
        const nextPending = (intent.needs_confirmation_json || []).filter((entry) => !sameConfirmation(entry, item));
        const currentValue = (intent as unknown as Record<string, unknown>)[item.field];
        const payload: Record<string, unknown> = { needs_confirmation_json: nextPending };
        if (action !== 'discard' && proposed !== undefined) payload[item.field] = mergeProposedValue(currentValue, proposed);
        if (action === 'deep_eval') payload.condition_effects_json = { ...(intent.condition_effects_json || {}), [item.field]: 'deep_eval' };
        await buyerIntents.update(intent.id, payload as BuyerIntentUpdate);
        await onRefresh?.();
      }
    } catch (error) {
      alert(error instanceof Error ? error.message : '处理待确认事项失败');
    } finally {
      setResolvingItem(null);
    }
  };

  const modifyPending = (item: PendingItem) => {
    const initial = item.proposed_value === undefined ? '' : JSON.stringify(item.proposed_value, null, 2);
    const input = window.prompt('修改建议值。数组或对象请填写合法 JSON；普通文字可直接填写。', initial);
    if (input === null) return;
    let value: unknown = input;
    try { value = JSON.parse(input); } catch { value = input.trim(); }
    void resolvePending(item, 'apply', value);
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
        registry ? <ContractEditor groups={registry.groups} indicators={indicators} fields={draft} effects={effects} taxonomy={taxonomy} onFields={setDraft} onEffects={setEffects} saving={saving} onSave={saveShared} /> : <Loading label="正在读取字段契约" />
      ) : (
        <ConditionDisplay title="公共条件" subtitle="与下面任一启用方案共同生效" groups={registry?.groups || []} indicators={indicators} fields={intent as unknown as Record<string, unknown>} effects={intent.condition_effects_json || {}} />
      )}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div><p className="text-xs font-semibold text-gray-500">需求方案</p><p className="mt-1 text-xs text-gray-400">匹配逻辑：公共条件 AND（任一启用方案）</p></div>
          <button type="button" onClick={() => void addScenario()} className="inline-flex items-center gap-1 border border-gray-200 px-3 py-1.5 text-xs text-gray-700 hover:border-brand-500 hover:text-brand-700"><Plus className="h-3.5 w-3.5" />新增方案</button>
        </div>
        {loadingScenarios ? <Loading label="正在读取方案" /> : scenarios.length ? scenarios.map((scenario) => (
          <ScenarioCard
            key={scenario.id}
            intentId={intent.id}
            scenario={scenario}
            groups={registry?.groups || []}
            indicators={indicators.filter((indicator) => indicator.scenario_allowed)}
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
          <div><p className="text-sm font-semibold text-gray-900">待确认事项</p><p className="mt-0.5 text-xs text-gray-500">确认前仅隔离存疑项：不参加初筛和软排序，但原始内容仍进入 AI 深评。</p></div>
          <button type="button" onClick={() => void completeReview()} disabled={reviewing} className="inline-flex items-center gap-1 bg-brand-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">
            {reviewing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}{allPending.length ? '完成复核' : '标记已复核'}
          </button>
        </div>
        <div className="divide-y divide-amber-100 px-4">
          {allPending.length ? allPending.map((item, index) => (
            <div key={`${confirmationKey(item)}-${index}`} className="py-3 text-sm">
              <div className="flex flex-wrap items-center gap-2"><EffectBadge effect="pending" /><span className="font-medium text-gray-900">{item.scopeLabel} · {indicatorLabel(indicators, item.field)}</span>{item.effect ? <EffectBadge effect={item.effect} /> : null}</div>
              <p className="mt-1 text-gray-700">{item.reason}</p>
              {item.proposed_value !== undefined ? <p className="mt-1 whitespace-pre-wrap text-xs text-gray-500">AI 建议值：{displayUnknown(item.proposed_value)}</p> : null}
              {item.evidence ? <p className="mt-1 text-xs text-gray-500">原文：{item.evidence}</p> : null}
              <div className="mt-2 flex flex-wrap gap-2">
                {item.proposed_value !== undefined ? <button type="button" disabled={resolvingItem === confirmationKey(item)} onClick={() => void resolvePending(item, 'apply')} className="border border-amber-300 bg-white px-2.5 py-1 text-xs text-amber-800 disabled:opacity-50">采纳建议值</button> : null}
                {item.proposed_value !== undefined ? <button type="button" disabled={resolvingItem === confirmationKey(item)} onClick={() => modifyPending(item)} className="border border-gray-200 bg-white px-2.5 py-1 text-xs text-gray-600 disabled:opacity-50">修改并采纳</button> : null}
                <button type="button" disabled={resolvingItem === confirmationKey(item)} onClick={() => void resolvePending(item, 'deep_eval')} className="border border-violet-200 bg-white px-2.5 py-1 text-xs text-violet-700 disabled:opacity-50">改为仅深评</button>
                <button type="button" disabled={resolvingItem === confirmationKey(item)} onClick={() => void resolvePending(item, 'discard')} className="border border-gray-200 bg-white px-2.5 py-1 text-xs text-gray-600 disabled:opacity-50">不设置该条件</button>
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

function ContractEditor({ groups, indicators, fields, effects, taxonomy, onFields, onEffects, saving, onSave }: {
  groups: IndicatorGroupMeta[];
  indicators: IndicatorMeta[];
  fields: Record<string, unknown>;
  effects: Record<string, ConditionEffect>;
  taxonomy: IndustryOptionsResponse;
  onFields: (value: Record<string, unknown>) => void;
  onEffects: (value: Record<string, ConditionEffect>) => void;
  saving: boolean;
  onSave: () => void;
}) {
  const setField = (field: string, value: unknown) => onFields({ ...fields, [field]: value });
  const setFields = (changes: Record<string, unknown>) => onFields({ ...fields, ...changes });
  const setEffect = (field: string, effect: ConditionEffect) => onEffects({ ...effects, [field]: effect });
  return (
    <section className="space-y-5 border border-brand-200 bg-brand-50/20 p-4">
      {groups.map((group) => {
        const groupIndicators = indicators.filter((indicator) => indicator.group === group.key);
        if (!groupIndicators.length) return null;
        return (
          <div key={group.key} className="space-y-3">
            <p className="border-b border-gray-200 pb-2 text-sm font-semibold text-gray-800">{group.label}</p>
            {group.key === 'intent_scope' ? (
              <IndustryFieldsEditor indicators={groupIndicators} fields={fields} effects={effects} taxonomy={taxonomy} setFields={setFields} setEffect={setEffect} />
            ) : null}
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {groupIndicators.filter((indicator) => !INDUSTRY_FIELDS.has(indicator.column)).map((indicator) => (
                <FieldEditor key={indicator.column} indicator={indicator} value={fields[indicator.column]} effect={effects[indicator.column] || indicator.default_effect || 'deep_eval'} onValue={(value) => setField(indicator.column, value)} onEffect={(effect) => setEffect(indicator.column, effect)} />
              ))}
            </div>
          </div>
        );
      })}
      <div className="flex justify-end"><button type="button" onClick={onSave} disabled={saving} className="inline-flex items-center gap-1 bg-brand-600 px-4 py-2 text-sm text-white disabled:opacity-50">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}保存</button></div>
    </section>
  );
}

const INDUSTRY_FIELDS = new Set(['industries_json', 'industry_l2_json', 'excluded_industries_json']);

function IndustryFieldsEditor({ indicators, fields, effects, taxonomy, setFields, setEffect }: {
  indicators: IndicatorMeta[];
  fields: Record<string, unknown>;
  effects: Record<string, ConditionEffect>;
  taxonomy: IndustryOptionsResponse;
  setFields: (fields: Record<string, unknown>) => void;
  setEffect: (field: string, effect: ConditionEffect) => void;
}) {
  const l1Indicator = indicators.find((item) => item.column === 'industries_json');
  const l2Indicator = indicators.find((item) => item.column === 'industry_l2_json');
  const excludedIndicator = indicators.find((item) => item.column === 'excluded_industries_json');
  const pairs = requirementPairs(fields, taxonomy);
  const excludedPairs = industryTermsToPairs(stringArray(fields.excluded_industries_json), taxonomy);
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      {l1Indicator && l2Indicator ? <div><div className="mb-2 flex flex-wrap items-center justify-between gap-2"><span className="text-xs font-medium text-gray-600">可接受行业</span><div className="flex gap-2"><EffectSelect label="一级" value={effects.industries_json || l1Indicator.default_effect || 'required'} onChange={(value) => setEffect('industries_json', value)} /><EffectSelect label="二级" value={effects.industry_l2_json || l2Indicator.default_effect || 'preferred'} onChange={(value) => setEffect('industry_l2_json', value)} /></div></div><IndustryPairsEditor value={pairs} options={taxonomy} onChange={(value) => setFields({ industries_json: [...new Set(value.map((pair) => pair.l1))], industry_l2_json: [...new Set(value.flatMap((pair) => pair.l2 ? [pair.l2] : []))] })} /></div> : null}
      {excludedIndicator ? <div><div className="mb-2 flex items-center justify-between gap-2"><span className="text-xs font-medium text-gray-600">排除行业</span><EffectBadge effect="required" /></div><IndustryPairsEditor value={excludedPairs} options={taxonomy} onChange={(value) => setFields({ excluded_industries_json: [...new Set(value.map((pair) => pair.l2 || pair.l1))] })} /></div> : null}
    </div>
  );
}

function FieldEditor({ indicator, value, effect, onValue, onEffect }: {
  indicator: IndicatorMeta;
  value: unknown;
  effect: ConditionEffect;
  onValue: (value: unknown) => void;
  onEffect: (value: ConditionEffect) => void;
}) {
  const header = <div className="mb-1 flex items-center justify-between gap-2"><span className="text-xs font-medium text-gray-600">{indicator.label}</span>{indicator.effect_editable && indicator.editor !== 'region_multi' ? <EffectSelect value={effect} onChange={onEffect} /> : <EffectBadge effect={effectiveEffect(indicator, {}, value)} />}</div>;
  if (indicator.editor === 'region_multi') return <div className="md:col-span-2 lg:col-span-3">{header}<RegionConstraintsEditor value={regionArray(value)} onChange={onValue} /></div>;
  if (indicator.editor === 'multi_enum') return <div>{header}<CheckboxOptions value={stringArray(value)} options={indicator.enum_options} onChange={onValue} /></div>;
  if (indicator.editor === 'tags') return <div>{header}<input className="input" value={stringArray(value).join('、')} onChange={(event) => onValue(splitTerms(event.target.value))} placeholder="多个值用顿号、逗号或换行分隔" /></div>;
  if (indicator.kind === 'enum') return <div>{header}<select className="input" value={stringValue(value, 'unknown')} onChange={(event) => onValue(event.target.value)}>{indicator.enum_options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></div>;
  if (indicator.kind === 'yuan' || indicator.kind === 'ratio') return <div>{header}<input className="input" type="number" value={stringValue(value)} onChange={(event) => onValue(event.target.value)} /></div>;
  if (indicator.editor === 'textarea' || indicator.group === 'intent_notes') return <div className="md:col-span-2 lg:col-span-3">{header}<textarea className="input min-h-20 resize-y" value={stringValue(value)} onChange={(event) => onValue(event.target.value)} /></div>;
  return <div>{header}<input className="input" value={stringValue(value)} onChange={(event) => onValue(event.target.value)} /></div>;
}

function RegionConstraintsEditor({ value, onChange }: { value: BuyerRegionConstraint[]; onChange: (value: BuyerRegionConstraint[]) => void }) {
  return (
    <div className="space-y-2 border border-gray-200 bg-gray-50 p-3">
      {value.map((item, index) => (
        <div key={`${item.province}-${item.city || ''}-${item.district || ''}-${index}`} className="grid gap-2 border-b border-gray-200 pb-2 lg:grid-cols-[1fr_8rem_auto]">
          <AdministrativeAreaPicker value={item} onChange={(area) => onChange(value.map((entry, itemIndex) => itemIndex === index ? { ...area, effect: item.effect } : entry))} />
          <select value={item.effect} onChange={(event) => onChange(value.map((entry, itemIndex) => itemIndex === index ? { ...entry, effect: event.target.value as BuyerRegionConstraint['effect'] } : entry))} className="border border-gray-200 bg-white px-2 py-1.5 text-xs"><option value="required">必须</option><option value="preferred">优先</option><option value="excluded">排除</option></select>
          <button type="button" onClick={() => onChange(value.filter((_, itemIndex) => itemIndex !== index))} className="text-xs text-red-600">移除</button>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...value, { province: '', effect: 'preferred' }])} className="inline-flex items-center gap-1 text-xs text-brand-700"><Plus className="h-3.5 w-3.5" />添加地区</button>
      <p className="text-[11px] text-gray-400">“全国”不生成地区条件；长三角、华东等由 AI 在规范化阶段展开为标准省份。</p>
    </div>
  );
}

function ScenarioCard({ intentId, scenario, groups, indicators, taxonomy, onSaved, onCopy, onDelete }: {
  intentId: string;
  scenario: BuyerIntentScenario;
  groups: IndicatorGroupMeta[];
  indicators: IndicatorMeta[];
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
  const [effects, setEffects] = useState<Record<string, ConditionEffect>>(scenario.condition_effects_json || {});

  useEffect(() => {
    setLabel(scenario.label); setSortOrder(String(scenario.sort_order)); setActive(scenario.active); setFields({ ...scenario.fields_json }); setEffects(scenario.condition_effects_json || {});
  }, [scenario]);

  const save = async () => {
    setSaving(true);
    try {
      const payload: BuyerIntentScenarioWrite = {
        label: label.trim() || scenario.label,
        sort_order: Number(sortOrder) || 0,
        active,
        fields_json: cleanFields(fields, indicators, true),
        needs_confirmation_json: scenario.needs_confirmation_json,
        condition_effects_json: effects,
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
    return (
      <div className={`border ${scenario.active ? 'border-gray-200 bg-white' : 'border-gray-200 bg-gray-50 opacity-70'}`}>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-4 py-3">
          <div className="flex items-center gap-2"><p className="text-sm font-semibold text-gray-900">{scenario.label}</p><StateBadge tone={scenario.active ? 'green' : 'gray'} text={scenario.active ? '启用' : '停用'} /><span className="text-xs text-gray-400">排序 {scenario.sort_order}</span></div>
          <div className="flex items-center gap-1"><IconButton title="复制" onClick={onCopy}><Copy className="h-3.5 w-3.5" /></IconButton><IconButton title="编辑" onClick={() => setEditing(true)}><Pencil className="h-3.5 w-3.5" /></IconButton><IconButton title="删除" onClick={onDelete}><Trash2 className="h-3.5 w-3.5" /></IconButton></div>
        </div>
        <ConditionDisplay title="" subtitle="" groups={groups} indicators={indicators} fields={scenario.fields_json} effects={scenario.condition_effects_json || {}} compact />
        <p className="border-t border-gray-100 px-4 py-2 text-xs text-gray-400">有效画像 = 公共条件 + 本方案条件</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 border border-brand-200 bg-brand-50/20 p-4">
      <div className="grid gap-4 md:grid-cols-3"><SimpleInput label="方案名称" value={label} onChange={setLabel} /><SimpleInput label="排序" type="number" value={sortOrder} onChange={setSortOrder} /><label className="block"><span className="mb-1 block text-xs font-medium text-gray-600">状态</span><select className="input" value={active ? 'active' : 'inactive'} onChange={(event) => setActive(event.target.value === 'active')}><option value="active">启用</option><option value="inactive">停用</option></select></label></div>
      <ContractEditor groups={groups} indicators={indicators} fields={fields} effects={effects} taxonomy={taxonomy} onFields={setFields} onEffects={setEffects} saving={saving} onSave={() => void save()} />
      <div className="flex justify-end"><button type="button" onClick={() => setEditing(false)} className="border border-gray-200 px-3 py-1.5 text-xs text-gray-600">取消</button></div>
    </div>
  );
}

function ConditionDisplay({ title, subtitle, groups, indicators, fields, effects, compact = false }: {
  title: string;
  subtitle: string;
  groups: IndicatorGroupMeta[];
  indicators: IndicatorMeta[];
  fields: Record<string, unknown>;
  effects: Record<string, ConditionEffect>;
  compact?: boolean;
}) {
  const rows = indicators.map((indicator) => ({ indicator, value: fields[indicator.column], effect: effectiveEffect(indicator, effects, fields[indicator.column]) })).filter(({ value }) => hasValue(value));
  return (
    <section className={compact ? '' : 'border border-gray-200'}>
      {title ? <SectionHeader title={title} subtitle={subtitle} /> : null}
      {rows.length ? groups.map((group) => {
        const groupRows = rows.filter(({ indicator }) => indicator.group === group.key);
        if (!groupRows.length) return null;
        return <div key={group.key} className="border-b border-gray-100 last:border-0"><p className="bg-gray-50 px-4 py-2 text-xs font-semibold text-gray-500">{group.label}</p><div className="divide-y divide-gray-100 px-4">{groupRows.map(({ indicator, value, effect }) => <ConditionLine key={indicator.column} label={indicator.label} value={formatFieldValue(indicator, value)} effect={effect} />)}</div></div>;
      }) : <p className="px-4 py-4 text-sm text-gray-500">暂无结构化条件。</p>}
    </section>
  );
}

function ConditionLine({ label, value, effect }: { label: string; value: string; effect: ConditionEffect }) {
  return <div className="flex items-start gap-3 py-2.5"><EffectBadge effect={effect} /><span className="w-32 shrink-0 text-xs text-gray-500">{label}</span><span className="min-w-0 whitespace-pre-wrap text-sm text-gray-800">{value}</span></div>;
}

function EffectBadge({ effect }: { effect: ConditionEffect | 'pending' }) {
  const styles = { required: 'bg-red-50 text-red-700', preferred: 'bg-blue-50 text-blue-700', deep_eval: 'bg-violet-50 text-violet-700', pending: 'bg-amber-100 text-amber-800' };
  const labels = { required: '必须', preferred: '优先', deep_eval: '仅深评', pending: '需要确认' };
  return <span className={`w-16 shrink-0 px-1.5 py-0.5 text-center text-[11px] font-medium ${styles[effect]}`}>{labels[effect]}</span>;
}

function EffectSelect({ value, onChange, label }: { value: ConditionEffect; onChange: (value: ConditionEffect) => void; label?: string }) {
  return <label className="flex items-center gap-1 text-[11px] text-gray-500">{label ? <span>{label}</span> : null}<select value={value} onChange={(event) => onChange(event.target.value as ConditionEffect)} className="border border-gray-200 bg-white px-1.5 py-1 text-[11px]"><option value="required">必须</option><option value="preferred">优先</option><option value="deep_eval">仅深评</option></select></label>;
}

function CheckboxOptions({ value, options, onChange }: { value: string[]; options: Array<{ value: string; label: string }>; onChange: (value: string[]) => void }) {
  return <div className="flex min-h-9 flex-wrap gap-2 border border-gray-200 bg-white p-2">{options.map((option) => <label key={option.value} className="inline-flex items-center gap-1 text-xs text-gray-700"><input type="checkbox" checked={value.includes(option.value)} onChange={() => onChange(value.includes(option.value) ? value.filter((item) => item !== option.value) : [...value, option.value])} />{option.label}</label>)}</div>;
}

function effectiveEffect(indicator: IndicatorMeta, effects: Record<string, ConditionEffect>, value: unknown): ConditionEffect {
  if (effects[indicator.column]) return effects[indicator.column];
  if (['requires_relocation', 'requires_return_investment', 'requires_team_retention'].includes(indicator.column)) {
    if (value === 'required' || value === 'preferred') return value;
    return 'deep_eval';
  }
  if (indicator.column === 'region_constraints_json') {
    const regions = regionArray(value);
    return regions.some((item) => item.effect === 'required' || item.effect === 'excluded') ? 'required' : 'preferred';
  }
  return indicator.default_effect || 'deep_eval';
}

function cleanFields(fields: Record<string, unknown>, indicators: IndicatorMeta[], scenario: boolean): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const indicator of indicators) {
    const value = fields[indicator.column];
    if (scenario && !hasValue(value)) continue;
    if (scenario && indicator.kind === 'enum' && value === 'unknown') continue;
    if (indicator.kind === 'yuan' || indicator.kind === 'ratio') {
      const number = value === '' || value === null || value === undefined ? null : Number(value);
      if (!scenario || Number.isFinite(number)) result[indicator.column] = Number.isFinite(number) ? number : null;
    } else if (indicator.kind === 'text') {
      result[indicator.column] = String(value || '').trim() || (scenario ? undefined : null);
    } else if (indicator.kind === 'json' && indicator.multi_value) {
      result[indicator.column] = Array.isArray(value) ? value : [];
    } else if (value !== undefined) {
      result[indicator.column] = value;
    }
  }
  return Object.fromEntries(Object.entries(result).filter(([, value]) => value !== undefined));
}

function intentDraft(intent: BuyerIntent): Record<string, unknown> {
  const source = intent as unknown as Record<string, unknown>;
  return Object.fromEntries(Object.entries(source).map(([key, value]) => [key, value ?? (key.endsWith('_json') ? [] : '')]));
}

function requirementPairs(fields: Record<string, unknown>, taxonomy: IndustryOptionsResponse): IndustryPairValue[] {
  const pairs: IndustryPairValue[] = stringArray(fields.industries_json).map((l1) => ({ l1 }));
  for (const l2 of stringArray(fields.industry_l2_json)) {
    const match = taxonomy.l2.find((item) => item.term === l2);
    if (match) pairs.push({ l1: match.l1, l2 });
  }
  return uniquePairs(pairs);
}

function industryTermsToPairs(terms: string[], taxonomy: IndustryOptionsResponse): IndustryPairValue[] {
  return uniquePairs(terms.map((term) => {
    const l2 = taxonomy.l2.find((item) => item.term === term);
    return l2 ? { l1: l2.l1, l2: l2.term } : { l1: term };
  }));
}

function uniquePairs(pairs: IndustryPairValue[]): IndustryPairValue[] {
  const seen = new Set<string>();
  return pairs.filter((pair) => { const key = `${pair.l1}:${pair.l2 || ''}`; if (seen.has(key)) return false; seen.add(key); return true; });
}

function formatFieldValue(indicator: IndicatorMeta, value: unknown): string {
  if (indicator.editor === 'region_multi') return regionArray(value).map((item) => `${item.province}${item.city || ''}${item.district || ''}（${item.effect === 'required' ? '必须' : item.effect === 'excluded' ? '排除' : '优先'}）`).join('、');
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
function stringValue(value: unknown, fallback = ''): string { return value === null || value === undefined ? fallback : String(value); }
function splitTerms(value: string): string[] { return [...new Set(value.split(/[、,，;；\n]/).map((item) => item.trim()).filter(Boolean))]; }
function hasValue(value: unknown): boolean { return value !== null && value !== undefined && value !== '' && value !== 'unknown' && (!Array.isArray(value) || value.length > 0); }
function moneyText(value: unknown): string { const number = Number(value); if (!Number.isFinite(number)) return String(value); if (Math.abs(number) < 10_000) return `${number.toFixed(0)}元`; if (Math.abs(number) < 100_000_000) return `${(number / 10_000).toFixed(0)}万`; return `${(number / 100_000_000).toFixed(1)}亿`; }
function displayUnknown(value: unknown): string { return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value); }
function indicatorLabel(indicators: IndicatorMeta[], field: string): string { return indicators.find((indicator) => indicator.column === field)?.label || field; }
function confirmationKey(item: PendingItem): string { return `${item.scopeLabel}:${item.item_key || item.field}:${item.uncertain_part || ''}`; }
function sameConfirmation(left: BuyerIntentConfirmationItem, right: BuyerIntentConfirmationItem): boolean { if (left.item_key || right.item_key) return left.item_key === right.item_key; return left.field === right.field && (left.evidence || '') === (right.evidence || '') && left.reason === right.reason; }
function SectionHeader({ title, subtitle }: { title: string; subtitle: string }) { return <div className="border-b border-gray-100 px-4 py-3"><p className="text-sm font-semibold text-gray-900">{title}</p><p className="mt-0.5 text-xs text-gray-400">{subtitle}</p></div>; }
function StateBadge({ tone, text }: { tone: 'amber' | 'green' | 'gray'; text: string }) { const style = tone === 'amber' ? 'bg-amber-50 text-amber-700' : tone === 'green' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600'; return <span className={`px-2 py-0.5 text-xs font-medium ${style}`}>{text}</span>; }
function IconButton({ title, onClick, children }: { title: string; onClick: () => void; children: ReactNode }) { return <button type="button" title={title} onClick={onClick} className="p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700">{children}</button>; }
function Loading({ label }: { label: string }) { return <div className="flex items-center justify-center border border-gray-100 py-8 text-sm text-gray-400"><Loader2 className="mr-2 h-4 w-4 animate-spin" />{label}</div>; }
function SimpleInput({ label, value, onChange, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; type?: string }) { return <label className="block"><span className="mb-1 block text-xs font-medium text-gray-600">{label}</span><input type={type} className="input" value={value} onChange={(event) => onChange(event.target.value)} /></label>; }
