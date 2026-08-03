import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  X,
} from 'lucide-react';
import { buyerIntents, fieldSources, indicatorRegistry, meta, profileSections } from '../lib/api';
import type {
  BuyerIntent,
  BuyerIntentConfirmationItem,
  BuyerIntentParseStatus,
  BuyerIntentScenario,
  BuyerIntentUpdate,
  BuyerRegionConstraint,
  ConditionEffect,
  IndicatorGroupMeta,
  IndicatorMeta,
  IndicatorRegistryResponse,
  IndustryOptionsResponse,
  FieldValueSource,
  ProfileSection,
} from '../types/api';
import IndustryPairsEditor, { type IndustryPairValue } from './IndustryPairsEditor';
import { hasReadableEvidence, sourceDetailText } from '../features/shared/fieldSource';
import { fieldLabel } from '../lib/fieldLabels';
import AdministrativeAreaPicker from './AdministrativeAreaPicker';

// 规则只有两态（ConditionEffect 定义在 types/api.ts，跟着接口契约走）：必须是
// 初筛硬门槛、优先只影响排序。标准化不了、不适合初筛的内容不再逐字段标「仅深评」，
// 统一进模块的「其他」。
type PendingItem = BuyerIntentConfirmationItem & { scopeLabel: string; scenario?: BuyerIntentScenario };
type ConditionRowDefinition = {
  key: string;
  label: string;
  group: string;
  indicators: IndicatorMeta[];
};

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
  const [resolvingItem, setResolvingItem] = useState<string | null>(null);
  const [sections, setSections] = useState<Record<string, ProfileSection>>({});
  const [sources, setSources] = useState<FieldValueSource[]>([]);
  const [openEvidence, setOpenEvidence] = useState<FieldValueSource | null>(null);

  const loadSideData = useCallback(async () => {
    const [sectionData, sourceData] = await Promise.all([
      profileSections.list('buyer_intent', intent.id).catch(() => null),
      fieldSources.list({ entity_type: 'buyer_intent', entity_id: intent.id, limit: 200 }).catch(() => []),
    ]);
    if (sectionData) {
      setSections(Object.fromEntries(sectionData.sections.map((item) => [item.section_code, item])));
    }
    setSources(sourceData);
  }, [intent.id]);

  const loadScenarios = useCallback(async () => {
    setLoadingScenarios(true);
    try {
      setScenarios(await buyerIntents.scenarios(intent.id));
    } finally {
      setLoadingScenarios(false);
    }
  }, [intent.id]);

  useEffect(() => { void loadScenarios(); }, [loadScenarios]);
  useEffect(() => { void loadSideData(); }, [loadSideData]);
  useEffect(() => {
    Promise.all([meta.industryOptions(), indicatorRegistry.list('buyer_intent')])
      .then(([industryData, registryData]) => { setTaxonomy(industryData); setRegistry(registryData); })
      .catch(() => {});
  }, []);

  const indicators = registry?.indicators || [];
  // 一个字段可能被写过多次，接口按时间倒序返回，第一条就是当前值的来源。
  const sourceByField = useMemo(() => {
    const map = new Map<string, FieldValueSource>();
    for (const source of sources) {
      if (!map.has(source.field_path)) map.set(source.field_path, source);
    }
    return map;
  }, [sources]);
  const commonPending = useMemo<PendingItem[]>(
    () => (intent.needs_confirmation_json || []).map((item) => ({ ...item, scopeLabel: '公共条件' })),
    [intent.needs_confirmation_json],
  );
  const pendingCount = commonPending.length + scenarios.reduce(
    (total, scenario) => total + (scenario.needs_confirmation_json || []).length,
    0,
  );

  const saveSharedConditions = async (
    changes: Record<string, unknown>,
    effectChanges: Record<string, ConditionEffect>,
  ) => {
    const payload = normalizeCommonFieldChanges(changes, indicators) as BuyerIntentUpdate;
    if (Object.keys(effectChanges).length) {
      payload.condition_effects_json = {
        ...(intent.condition_effects_json || {}),
        ...effectChanges,
      };
    }
    await buyerIntents.update(intent.id, payload);
    await onRefresh?.();
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

  const resolvePending = async (
    item: PendingItem,
    action: 'apply' | 'discard',
    replacement?: unknown,
  ) => {
    const key = confirmationKey(item);
    setResolvingItem(key);
    try {
      const rawProposed = replacement === undefined ? item.proposed_value : replacement;
      let proposed = rawProposed;
      if (action === 'apply') {
        const indicator = indicators.find((entry) => entry.column === item.field);
        const normalized = normalizePendingProposedValue(indicator, rawProposed);
        if (
          replacement === undefined
          && (item.proposed_value_status || (item.uncertain_part && item.uncertain_part !== 'value'))
        ) {
          throw new Error('该建议包含类型、作用范围或规则含义的不确定性，请修改为合法字段值后再采纳。');
        }
        if (!normalized.valid) {
          throw new Error('建议值不符合字段类型，请修改后再采纳。');
        }
        proposed = normalized.value;
      }
      if (item.scenario) {
        const scenario = item.scenario;
        const nextPending = scenario.needs_confirmation_json.filter((entry) => !sameConfirmation(entry, item));
        const currentValue = scenario.fields_json[item.field];
        const nextFields = action === 'discard' || proposed === undefined
          ? scenario.fields_json
          : { ...scenario.fields_json, [item.field]: mergeProposedValue(currentValue, proposed) };
        const updated = await buyerIntents.updateScenario(intent.id, scenario.id, {
          label: scenario.label,
          sort_order: scenario.sort_order,
          active: scenario.active,
          fields_json: nextFields,
          needs_confirmation_json: nextPending,
          condition_effects_json: scenario.condition_effects_json,
        });
        setScenarios((current) => current.map((entry) => entry.id === updated.id ? updated : entry));
      } else {
        const nextPending = (intent.needs_confirmation_json || []).filter((entry) => !sameConfirmation(entry, item));
        const currentValue = (intent as unknown as Record<string, unknown>)[item.field];
        const payload: Record<string, unknown> = { needs_confirmation_json: nextPending };
        if (action !== 'discard' && proposed !== undefined) payload[item.field] = mergeProposedValue(currentValue, proposed);
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
        {pendingCount ? <StateBadge tone="amber" text={`${pendingCount} 项需要确认`} /> : null}
      </div>

      {registry ? (
        <InlineConditionEditor
          title="公共条件"
          subtitle="与下面任一启用方案共同生效；点击字段即可单独编辑和保存"
          groups={registry.groups}
          indicators={indicators}
          fields={intent as unknown as Record<string, unknown>}
          effects={intent.condition_effects_json || {}}
          taxonomy={taxonomy}
          pending={commonPending}
          resolvingItem={resolvingItem}
          sourceByField={sourceByField}
          onShowEvidence={setOpenEvidence}
          notesByGroup={Object.fromEntries(registry.groups.map((group) => [
            group.key,
            <ModuleNotes
              key={group.key}
              intentId={intent.id}
              sectionCode={group.section_code || group.key}
              label={group.label}
              descriptiveIndicators={indicators.filter((item) => item.group === group.key && !isConditionIndicator(item))}
              fields={intent as unknown as Record<string, unknown>}
              section={sections[group.section_code || group.key]}
              onSaved={loadSideData}
            />,
          ]))}
          onSave={saveSharedConditions}
          onResolvePending={resolvePending}
          onModifyPending={modifyPending}
        />
      ) : <Loading label="正在读取字段契约" />}

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
            resolvingItem={resolvingItem}
            onSaved={(updated) => setScenarios((current) => current.map((item) => item.id === updated.id ? updated : item))}
            onCopy={() => void copyScenario(scenario)}
            onDelete={() => void deleteScenario(scenario)}
            onResolvePending={resolvePending}
            onModifyPending={modifyPending}
          />
        )) : (
          <div className="border border-dashed border-gray-200 px-4 py-5 text-sm text-gray-500">未设置显式方案，当前需求按一套公共条件进行匹配。</div>
        )}
      </section>

      {openEvidence ? <EvidencePopover source={openEvidence} onClose={() => setOpenEvidence(null)} /> : null}

      <section>
        <p className="mb-2 text-xs font-semibold text-gray-500">原始需求材料</p>
        <p className="max-h-72 overflow-y-auto whitespace-pre-wrap bg-gray-50 px-4 py-3 text-sm leading-6 text-gray-700">{intent.raw_requirement_text || '暂无原始需求材料'}</p>
      </section>
    </div>
  );
}

function InlineConditionEditor({
  title,
  subtitle,
  groups,
  indicators,
  fields,
  effects,
  taxonomy,
  pending,
  resolvingItem,
  showEmpty = true,
  notesByGroup,
  sourceByField,
  onShowEvidence,
  onSave,
  onResolvePending,
  onModifyPending,
}: {
  title: string;
  subtitle: string;
  groups: IndicatorGroupMeta[];
  indicators: IndicatorMeta[];
  fields: Record<string, unknown>;
  effects: Record<string, ConditionEffect>;
  taxonomy: IndustryOptionsResponse;
  pending: PendingItem[];
  resolvingItem: string | null;
  showEmpty?: boolean;
  /** 每个模块底部那块「其他」，由调用方渲染 —— 方案卡片没有。 */
  notesByGroup?: Record<string, ReactNode>;
  /** 字段当前值的出处。方案卡片不传：方案条件是人配的，没有独立溯源。 */
  sourceByField?: Map<string, FieldValueSource>;
  onShowEvidence?: (source: FieldValueSource) => void;
  onSave: (changes: Record<string, unknown>, effectChanges: Record<string, ConditionEffect>) => Promise<void>;
  onResolvePending: (item: PendingItem, action: 'apply' | 'discard', replacement?: unknown) => Promise<void>;
  onModifyPending: (item: PendingItem) => void;
}) {
  const rows = useMemo(() => conditionRows(indicators), [indicators]);
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [draftFields, setDraftFields] = useState<Record<string, unknown>>({});
  const [draftEffects, setDraftEffects] = useState<Record<string, ConditionEffect>>({});
  const [saving, setSaving] = useState(false);

  const startEditing = (row: ConditionRowDefinition) => {
    setDraftFields(Object.fromEntries(row.indicators.map((indicator) => [indicator.column, fields[indicator.column]])));
    setDraftEffects(Object.fromEntries(
      row.indicators
        .filter((indicator) => indicator.effect_editable && indicator.editor !== 'region_multi')
        .flatMap((indicator) => {
          // 草稿只装真规则。眼下每个可编辑字段都有 default_effect，这里取不到 null；
          // 真出现了也宁可不进草稿（保存时不碰这个字段），也别把 null 写进
          // condition_effects_json —— 那是个后端会当垃圾丢掉的值。
          const effect = effectiveEffect(indicator, effects, fields[indicator.column]);
          return effect ? [[indicator.column, effect] as const] : [];
        }),
    ));
    setEditingKey(row.key);
  };

  const saveRow = async () => {
    setSaving(true);
    try {
      await onSave(draftFields, draftEffects);
      setEditingKey(null);
    } catch (error) {
      alert(error instanceof Error ? error.message : '保存字段失败');
    } finally {
      setSaving(false);
    }
  };

  const pendingForRow = (row: ConditionRowDefinition) => pending.filter(
    (item) => row.indicators.some((indicator) => indicator.column === item.field),
  );
  const isVisible = (row: ConditionRowDefinition) => showEmpty
    || row.indicators.some((indicator) => hasValue(fields[indicator.column]))
    || pendingForRow(row).length > 0
    || editingKey === row.key;
  const hiddenRows = rows.filter((row) => !isVisible(row));
  const orphanPending = pending.filter(
    (item) => !rows.some((row) => row.indicators.some((indicator) => indicator.column === item.field)),
  );

  return (
    <section className="border border-gray-200 bg-white">
      {(title || !showEmpty) ? (
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-4 py-3">
          <div>{title ? <p className="text-sm font-semibold text-gray-900">{title}</p> : null}{subtitle ? <p className="mt-0.5 text-xs text-gray-400">{subtitle}</p> : null}</div>
          {!showEmpty && hiddenRows.length ? (
            <select
              value=""
              onChange={(event) => {
                const row = rows.find((item) => item.key === event.target.value);
                if (row) startEditing(row);
              }}
              className="border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-700"
            >
              <option value="">新增条件…</option>
              {hiddenRows.map((row) => <option key={row.key} value={row.key}>{row.label}</option>)}
            </select>
          ) : null}
        </div>
      ) : null}

      {groups.map((group) => {
        const groupRows = rows.filter((row) => row.group === group.key && isVisible(row));
        const groupAllRows = rows.filter((row) => row.group === group.key);
        const filled = groupAllRows.filter((row) => row.indicators.some((indicator) => hasValue(fields[indicator.column]))).length;
        const notes = notesByGroup?.[group.key];
        if (!groupRows.length && !notes) return null;
        const collapsed = collapsedGroups[group.key] ?? false;
        return (
          <div key={group.key} className="border-b border-gray-100 last:border-0">
            <button
              type="button"
              onClick={() => setCollapsedGroups((prev) => ({ ...prev, [group.key]: !collapsed }))}
              className="flex w-full items-center justify-between bg-gray-50 px-4 py-2 text-left hover:bg-gray-100"
            >
              <span className="flex items-center gap-1.5 text-xs font-semibold text-gray-600">
                {collapsed ? <ChevronRight className="h-3.5 w-3.5 text-gray-400" /> : <ChevronDown className="h-3.5 w-3.5 text-gray-400" />}
                {group.label}
              </span>
              <span className="text-[11px] text-gray-400">{filled}/{groupAllRows.length} 条件{notes ? ' · 含其他' : ''}</span>
            </button>
            {collapsed ? null : (
            <div className="divide-y divide-gray-100 px-4">
              {groupRows.map((row) => {
                const rowPending = pendingForRow(row);
                const editing = editingKey === row.key;
                const rowHasValue = row.indicators.some((indicator) => hasValue(fields[indicator.column]));
                return (
                  <div key={row.key} className="py-3">
                    {editing ? (
                      <div className="space-y-3">
                        <ConditionRowEditor
                          row={row}
                          fields={draftFields}
                          effects={draftEffects}
                          taxonomy={taxonomy}
                          onFields={setDraftFields}
                          onEffects={setDraftEffects}
                        />
                        <div className="flex justify-end gap-2">
                          <button type="button" disabled={saving} onClick={() => void saveRow()} className="inline-flex items-center gap-1 bg-brand-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}保存</button>
                          <button type="button" disabled={saving} onClick={() => setEditingKey(null)} className="inline-flex items-center gap-1 border border-gray-200 px-3 py-1.5 text-xs text-gray-600"><X className="h-3.5 w-3.5" />取消</button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-start gap-3">
                        <div className="flex w-20 shrink-0 flex-wrap gap-1">
                          {rowHasValue ? row.indicators.filter((indicator) => hasValue(fields[indicator.column])).map((indicator) => (
                            <EffectBadge key={indicator.column} effect={effectiveEffect(indicator, effects, fields[indicator.column])} />
                          )) : <span className="px-1.5 py-0.5 text-[11px] text-gray-400">未设置</span>}
                        </div>
                        <span className="w-36 shrink-0 text-xs text-gray-500">{row.label}</span>
                        <span className={`min-w-0 flex-1 whitespace-pre-wrap text-sm ${rowHasValue ? 'text-gray-800' : 'text-gray-300'}`}>{formatConditionRow(row, fields, taxonomy)}</span>
                        {rowPending.length ? <StateBadge tone="amber" text={`${rowPending.length} 项待确认`} /> : null}
                        <button type="button" title={`编辑${row.label}`} onClick={() => startEditing(row)} className="p-1.5 text-gray-400 hover:bg-gray-100 hover:text-brand-700"><Pencil className="h-3.5 w-3.5" /></button>
                      </div>
                    )}
                    {!editing && rowHasValue && sourceByField ? (
                      <RowSource
                        row={row}
                        sourceByField={sourceByField}
                        onShowEvidence={onShowEvidence}
                      />
                    ) : null}
                    {rowPending.length ? (
                      <PendingItems
                        items={rowPending}
                        resolvingItem={resolvingItem}
                        onResolve={onResolvePending}
                        onModify={onModifyPending}
                        indicators={indicators}
                      />
                    ) : null}
                  </div>
                );
              })}
              {notes}
            </div>
            )}
          </div>
        );
      })}

      {orphanPending.map((item, index) => (
        <div key={`${confirmationKey(item)}:${index}`} className="border-t border-amber-100 px-4 py-3">
          <div className="flex items-center gap-3"><EffectBadge effect="pending" /><span className="text-xs text-gray-500">{item.field}</span></div>
          <PendingItems items={[item]} resolvingItem={resolvingItem} onResolve={onResolvePending} onModify={onModifyPending} indicators={indicators} />
        </div>
      ))}

      {!showEmpty && !rows.some(isVisible) && !orphanPending.length ? <p className="px-4 py-4 text-sm text-gray-500">暂无方案条件，可从右上角新增。</p> : null}
    </section>
  );
}

/** 一行可能由多个字段组成（如行业的一级+二级），取第一条有出处的。 */
function RowSource({ row, sourceByField, onShowEvidence }: {
  row: ConditionRowDefinition;
  sourceByField: Map<string, FieldValueSource>;
  onShowEvidence?: (source: FieldValueSource) => void;
}) {
  const source = row.indicators.map((indicator) => sourceByField.get(indicator.column)).find(Boolean);
  if (!source) return null;
  const text = `来源：${sourceDetailText(source)}`;
  if (onShowEvidence && hasReadableEvidence(source)) {
    return (
      <button type="button" onClick={() => onShowEvidence(source)} className="ml-[7.5rem] block text-left text-[10px] text-gray-400 hover:text-brand-600 hover:underline">
        {text}
      </button>
    );
  }
  return <p className="ml-[7.5rem] text-[10px] text-gray-400">{text}</p>;
}

/**
 * 模块底部的「其他」：装这个模块里标准化不了、也不适合拿去初筛的说法。
 *
 * 上面是只读的描述字段（解析写进来的，如溢价要求、风险容忍），下面是一块自由
 * 文本，人可以直接改。两者都会随搜索文档进深评 —— 「放进其他就交给深评」这句
 * 话对模型也成立，不只是界面上的说法。
 */
function ModuleNotes({ intentId, sectionCode, label, descriptiveIndicators, fields, section, onSaved }: {
  intentId: string;
  sectionCode: string;
  label: string;
  descriptiveIndicators: IndicatorMeta[];
  fields: Record<string, unknown>;
  section?: ProfileSection;
  onSaved: () => void | Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);

  const filled = descriptiveIndicators.filter((indicator) => hasValue(fields[indicator.column]));
  const content = (section?.content_text || '').trim();
  if (!filled.length && !content && !editing) {
    return (
      <div className="py-3">
        <button type="button" onClick={() => { setDraft(''); setEditing(true); }} className="text-xs text-gray-400 hover:text-brand-700">
          + 补充「{label}」的其他说明
        </button>
      </div>
    );
  }

  const save = async () => {
    setSaving(true);
    try {
      await profileSections.write('buyer_intent', intentId, {
        section_code: sectionCode,
        info_status: 'filled',
        content_text: draft.trim() || null,
      });
      setEditing(false);
      await onSaved();
    } catch (error) {
      alert(error instanceof Error ? error.message : '保存其他说明失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="py-3">
      <p className="mb-1.5 text-[11px] font-semibold text-gray-400">其他（不参与初筛，交给深度评估）</p>
      {filled.map((indicator) => (
        <div key={indicator.column} className="flex items-start gap-3 py-1">
          <span className="w-16 shrink-0" />
          <span className="w-36 shrink-0 text-xs text-gray-500">{indicator.label}</span>
          <span className="min-w-0 flex-1 whitespace-pre-wrap text-sm text-gray-700">{displayDescriptive(fields[indicator.column])}</span>
        </div>
      ))}
      {editing ? (
        <div className="mt-2 space-y-2">
          <textarea className="input min-h-24 resize-y" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={`这个模块里标准化不了的说法，写在这里`} />
          <div className="flex justify-end gap-2">
            <button type="button" disabled={saving} onClick={() => void save()} className="inline-flex items-center gap-1 bg-brand-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}保存</button>
            <button type="button" disabled={saving} onClick={() => setEditing(false)} className="inline-flex items-center gap-1 border border-gray-200 px-3 py-1.5 text-xs text-gray-600"><X className="h-3.5 w-3.5" />取消</button>
          </div>
        </div>
      ) : (
        <div className="mt-1 flex items-start gap-3 py-1">
          <span className="w-16 shrink-0" />
          <span className="w-36 shrink-0 text-xs text-gray-500">其他说明</span>
          <span className={`min-w-0 flex-1 whitespace-pre-wrap text-sm ${content ? 'text-gray-700' : 'text-gray-300'}`}>{content || '未填写'}</span>
          <button type="button" title="编辑其他说明" onClick={() => { setDraft(content); setEditing(true); }} className="p-1.5 text-gray-400 hover:bg-gray-100 hover:text-brand-700"><Pencil className="h-3.5 w-3.5" /></button>
        </div>
      )}
    </div>
  );
}

/** 字段值的出处。附件解析给的是正文片段，AI 调研给的是网页。 */
function EvidencePopover({ source, onClose }: { source: FieldValueSource; onClose: () => void }) {
  const excerpt = source.evidence_span?.text_excerpt || source.research_evidence?.source_excerpt || '';
  const url = source.research_evidence?.source_url || '';
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-end bg-black/20 p-4 sm:items-center" onClick={onClose}>
      <div className="max-h-[70vh] w-full max-w-xl overflow-y-auto border border-gray-200 bg-white p-4 shadow-lg" onClick={(event) => event.stopPropagation()}>
        <div className="mb-2 flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-gray-900">{fieldLabel('buyer_intent', source.field_path)}</p>
            <p className="mt-0.5 text-xs text-gray-500">{sourceDetailText(source)}</p>
          </div>
          <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700"><X className="h-4 w-4" /></button>
        </div>
        {url ? <a href={url} target="_blank" rel="noreferrer" className="mb-2 block break-all text-xs text-brand-700 underline">{source.research_evidence?.source_title || url}</a> : null}
        <p className="whitespace-pre-wrap bg-gray-50 px-3 py-2 text-sm leading-6 text-gray-700">{excerpt || '这条来源没有留存原文片段。'}</p>
      </div>
    </div>
  );
}

function displayDescriptive(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => String(item)).join('、');
  if (value === null || value === undefined || value === '') return '-';
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
}

function ConditionRowEditor({ row, fields, effects, taxonomy, onFields, onEffects }: {
  row: ConditionRowDefinition;
  fields: Record<string, unknown>;
  effects: Record<string, ConditionEffect>;
  taxonomy: IndustryOptionsResponse;
  onFields: (value: Record<string, unknown>) => void;
  onEffects: (value: Record<string, ConditionEffect>) => void;
}) {
  const setField = (field: string, value: unknown) => onFields({ ...fields, [field]: value });
  const setEffect = (field: string, effect: ConditionEffect) => onEffects({ ...effects, [field]: effect });

  if (row.key === 'accepted_industries') {
    const l1Indicator = row.indicators.find((item) => item.column === 'industries_json');
    const l2Indicator = row.indicators.find((item) => item.column === 'industry_l2_json');
    return (
      <div>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-medium text-gray-600">可接受行业</span>
          <div className="flex gap-2">
            {l1Indicator ? <EffectSelect label="一级" value={effects.industries_json || l1Indicator.default_effect || 'required'} onChange={(value) => setEffect('industries_json', value)} /> : null}
            {l2Indicator ? <EffectSelect label="二级" value={effects.industry_l2_json || l2Indicator.default_effect || 'preferred'} onChange={(value) => setEffect('industry_l2_json', value)} /> : null}
          </div>
        </div>
        <IndustryPairsEditor
          value={requirementPairs(fields, taxonomy)}
          options={taxonomy}
          onChange={(value) => onFields({
            ...fields,
            industries_json: [...new Set(value.map((pair) => pair.l1))],
            industry_l2_json: [...new Set(value.flatMap((pair) => pair.l2 ? [pair.l2] : []))],
          })}
        />
      </div>
    );
  }

  const indicator = row.indicators[0];
  if (indicator.column === 'excluded_industries_json') {
    return (
      <div>
        <div className="mb-2 flex items-center justify-between gap-2"><span className="text-xs font-medium text-gray-600">{indicator.label}</span><EffectBadge effect="required" /></div>
        <IndustryPairsEditor
          value={industryTermsToPairs(stringArray(fields.excluded_industries_json), taxonomy)}
          options={taxonomy}
          onChange={(value) => setField('excluded_industries_json', [...new Set(value.map((pair) => pair.l2 || pair.l1))])}
        />
      </div>
    );
  }

  return (
    <FieldEditor
      indicator={indicator}
      value={fields[indicator.column]}
      effect={effects[indicator.column] || effectiveEffect(indicator, {}, fields[indicator.column])}
      onValue={(value) => setField(indicator.column, value)}
      onEffect={(effect) => setEffect(indicator.column, effect)}
    />
  );
}

function PendingItems({ items, resolvingItem, onResolve, onModify, indicators }: {
  items: PendingItem[];
  resolvingItem: string | null;
  onResolve: (item: PendingItem, action: 'apply' | 'discard', replacement?: unknown) => Promise<void>;
  onModify: (item: PendingItem) => void;
  indicators: IndicatorMeta[];
}) {
  return (
    <div className="mt-3 divide-y divide-amber-100 border border-amber-200 bg-amber-50/50 px-3">
      {items.map((item, index) => {
        const key = confirmationKey(item);
        const indicator = indicators.find((entry) => entry.column === item.field);
        const normalized = normalizePendingProposedValue(indicator, item.proposed_value);
        const canApplyDirectly = item.proposed_value !== undefined
          && !item.proposed_value_status
          && (!item.uncertain_part || item.uncertain_part === 'value')
          && normalized.valid;
        return (
          <div key={`${key}:${index}`} className="py-3 text-sm">
            <div className="flex flex-wrap items-center gap-2"><EffectBadge effect="pending" />{item.effect ? <EffectBadge effect={item.effect} /> : null}<span className="text-xs text-gray-500">确认前不参加初筛和软排序</span></div>
            <p className="mt-1 text-gray-700">{item.reason}</p>
            {item.proposed_value !== undefined ? <p className="mt-1 whitespace-pre-wrap text-xs text-gray-500">AI 建议值：{displayUnknown(item.proposed_value)}</p> : null}
            {item.proposed_value !== undefined && !canApplyDirectly ? <p className="mt-1 text-xs text-amber-700">该值不能直接写入，请先修改为符合字段类型的明确值。</p> : null}
            {item.evidence ? <p className="mt-1 text-xs text-gray-500">原文：{item.evidence}</p> : null}
            <div className="mt-2 flex flex-wrap gap-2">
              {canApplyDirectly ? <button type="button" disabled={resolvingItem === key} onClick={() => void onResolve(item, 'apply')} className="border border-amber-300 bg-white px-2.5 py-1 text-xs text-amber-800 disabled:opacity-50">采纳建议值</button> : null}
              {item.proposed_value !== undefined ? <button type="button" disabled={resolvingItem === key} onClick={() => onModify(item)} className="border border-gray-200 bg-white px-2.5 py-1 text-xs text-gray-600 disabled:opacity-50">修改并采纳</button> : null}
              <button type="button" disabled={resolvingItem === key} onClick={() => void onResolve(item, 'discard')} className="border border-gray-200 bg-white px-2.5 py-1 text-xs text-gray-600 disabled:opacity-50">不设置该条件</button>
            </div>
          </div>
        );
      })}
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
  if (indicator.editor === 'region_multi') return <div>{header}<RegionConstraintsEditor value={regionArray(value)} onChange={onValue} /></div>;
  if (indicator.editor === 'multi_enum') return <div>{header}<CheckboxOptions value={stringArray(value)} options={indicator.enum_options} onChange={onValue} /></div>;
  if (indicator.editor === 'tags') return <div>{header}<input className="input" value={stringArray(value).join('、')} onChange={(event) => onValue(splitTerms(event.target.value))} placeholder="多个值用顿号、逗号或换行分隔" /></div>;
  if (indicator.kind === 'enum') return <div>{header}<select className="input" value={stringValue(value, 'unknown')} onChange={(event) => onValue(event.target.value)}>{indicator.enum_options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></div>;
  if (indicator.kind === 'yuan' || indicator.kind === 'ratio') return <div>{header}<input className="input" type="number" value={stringValue(value)} onChange={(event) => onValue(event.target.value)} /></div>;
  if (indicator.editor === 'textarea' || indicator.group === 'intent_notes') return <div>{header}<textarea className="input min-h-20 resize-y" value={stringValue(value)} onChange={(event) => onValue(event.target.value)} /></div>;
  return <div>{header}<input className="input" value={stringValue(value)} onChange={(event) => onValue(event.target.value)} /></div>;
}

export function RegionConstraintsEditor({ value, onChange }: { value: BuyerRegionConstraint[]; onChange: (value: BuyerRegionConstraint[]) => void }) {
  return (
    <div className="space-y-2 border border-gray-200 bg-gray-50 p-3">
      {value.map((item, index) => (
        <div key={`${item.province}-${item.city || ''}-${item.district || ''}-${index}`} className="grid min-w-0 gap-2 border-b border-gray-200 pb-2 lg:grid-cols-[minmax(0,1fr)_8rem_auto]">
          <AdministrativeAreaPicker value={item} onChange={(area) => onChange(value.map((entry, itemIndex) => itemIndex === index ? { ...area, effect: item.effect } : entry))} />
          <select value={item.effect} onChange={(event) => onChange(value.map((entry, itemIndex) => itemIndex === index ? { ...entry, effect: event.target.value as BuyerRegionConstraint['effect'] } : entry))} className="min-w-0 border border-gray-200 bg-white px-2 py-1.5 text-xs"><option value="required">必须</option><option value="preferred">优先</option><option value="excluded">排除</option></select>
          <button type="button" onClick={() => onChange(value.filter((_, itemIndex) => itemIndex !== index))} className="text-xs text-red-600">移除</button>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...value, { province: '', effect: 'preferred' }])} className="inline-flex items-center gap-1 text-xs text-brand-700"><Plus className="h-3.5 w-3.5" />添加地区</button>
      <p className="text-[11px] text-gray-400">“全国”不生成地区条件；长三角、华东等由 AI 在规范化阶段展开为标准省份。</p>
    </div>
  );
}

function ScenarioCard({
  intentId,
  scenario,
  groups,
  indicators,
  taxonomy,
  resolvingItem,
  onSaved,
  onCopy,
  onDelete,
  onResolvePending,
  onModifyPending,
}: {
  intentId: string;
  scenario: BuyerIntentScenario;
  groups: IndicatorGroupMeta[];
  indicators: IndicatorMeta[];
  taxonomy: IndustryOptionsResponse;
  resolvingItem: string | null;
  onSaved: (scenario: BuyerIntentScenario) => void;
  onCopy: () => void;
  onDelete: () => void;
  onResolvePending: (item: PendingItem, action: 'apply' | 'discard', replacement?: unknown) => Promise<void>;
  onModifyPending: (item: PendingItem) => void;
}) {
  const [editingMeta, setEditingMeta] = useState(false);
  const [savingMeta, setSavingMeta] = useState(false);
  const [label, setLabel] = useState(scenario.label);
  const [sortOrder, setSortOrder] = useState(String(scenario.sort_order));
  const [active, setActive] = useState(scenario.active);

  useEffect(() => {
    setLabel(scenario.label);
    setSortOrder(String(scenario.sort_order));
    setActive(scenario.active);
  }, [scenario]);

  const saveMetadata = async () => {
    setSavingMeta(true);
    try {
      onSaved(await buyerIntents.updateScenario(intentId, scenario.id, {
        label: label.trim() || scenario.label,
        sort_order: Number(sortOrder) || 0,
        active,
        fields_json: scenario.fields_json,
        needs_confirmation_json: scenario.needs_confirmation_json,
        condition_effects_json: scenario.condition_effects_json,
      }));
      setEditingMeta(false);
    } catch (error) {
      alert(error instanceof Error ? error.message : '保存方案信息失败');
    } finally {
      setSavingMeta(false);
    }
  };

  const saveScenarioConditions = async (
    changes: Record<string, unknown>,
    effectChanges: Record<string, ConditionEffect>,
  ) => {
    const changedFields = new Set(Object.keys(changes));
    const nextFields = applyScenarioFieldChanges(scenario.fields_json, changes, indicators);
    const nextEffects = { ...(scenario.condition_effects_json || {}) };
    for (const field of changedFields) {
      if (!(field in nextFields)) delete nextEffects[field];
    }
    Object.assign(nextEffects, effectChanges);
    const nextPending = scenario.needs_confirmation_json.filter((item) => !changedFields.has(item.field));
    onSaved(await buyerIntents.updateScenario(intentId, scenario.id, {
      label: scenario.label,
      sort_order: scenario.sort_order,
      active: scenario.active,
      fields_json: nextFields,
      needs_confirmation_json: nextPending,
      condition_effects_json: nextEffects,
    }));
  };

  const scenarioPending = (scenario.needs_confirmation_json || []).map((item) => ({
    ...item,
    scopeLabel: scenario.label,
    scenario,
  }));

  return (
    <div className={`border ${scenario.active ? 'border-gray-200 bg-white' : 'border-gray-200 bg-gray-50'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-4 py-3">
        {editingMeta ? (
          <div className="grid flex-1 gap-3 md:grid-cols-[minmax(12rem,1fr)_7rem_8rem_auto]">
            <SimpleInput label="方案名称" value={label} onChange={setLabel} />
            <SimpleInput label="排序" type="number" value={sortOrder} onChange={setSortOrder} />
            <label className="block"><span className="mb-1 block text-xs font-medium text-gray-600">状态</span><select className="input" value={active ? 'active' : 'inactive'} onChange={(event) => setActive(event.target.value === 'active')}><option value="active">启用</option><option value="inactive">停用</option></select></label>
            <div className="flex items-end gap-2"><button type="button" disabled={savingMeta} onClick={() => void saveMetadata()} className="inline-flex items-center gap-1 bg-brand-600 px-3 py-2 text-xs text-white disabled:opacity-50">{savingMeta ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}保存</button><button type="button" onClick={() => setEditingMeta(false)} className="border border-gray-200 px-3 py-2 text-xs text-gray-600">取消</button></div>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2"><p className="text-sm font-semibold text-gray-900">{scenario.label}</p><StateBadge tone={scenario.active ? 'green' : 'gray'} text={scenario.active ? '启用' : '停用'} /><span className="text-xs text-gray-400">排序 {scenario.sort_order}</span>{scenarioPending.length ? <StateBadge tone="amber" text={`${scenarioPending.length} 项待确认`} /> : null}</div>
            <div className="flex items-center gap-1"><IconButton title="复制" onClick={onCopy}><Copy className="h-3.5 w-3.5" /></IconButton><IconButton title="编辑方案名称、排序和状态" onClick={() => setEditingMeta(true)}><Pencil className="h-3.5 w-3.5" /></IconButton><IconButton title="删除" onClick={onDelete}><Trash2 className="h-3.5 w-3.5" /></IconButton></div>
          </>
        )}
      </div>

      <InlineConditionEditor
        title=""
        subtitle=""
        groups={groups}
        indicators={indicators}
        fields={scenario.fields_json}
        effects={scenario.condition_effects_json || {}}
        taxonomy={taxonomy}
        pending={scenarioPending}
        resolvingItem={resolvingItem}
        showEmpty={false}
        onSave={saveScenarioConditions}
        onResolvePending={onResolvePending}
        onModifyPending={onModifyPending}
      />
      <p className="border-t border-gray-100 px-4 py-2 text-xs text-gray-400">有效画像 = 公共条件 + 本方案条件</p>
    </div>
  );
}

function conditionRows(indicators: IndicatorMeta[]): ConditionRowDefinition[] {
  const rows: ConditionRowDefinition[] = [];
  const l2 = indicators.find((item) => item.column === 'industry_l2_json');
  for (const indicator of indicators) {
    if (!indicator.group || indicator.column === 'industry_l2_json') continue;
    if (!isConditionIndicator(indicator)) continue;
    if (indicator.column === 'industries_json') {
      rows.push({
        key: 'accepted_industries',
        label: '可接受行业',
        group: indicator.group,
        indicators: l2 ? [indicator, l2] : [indicator],
      });
      continue;
    }
    rows.push({ key: indicator.column, label: indicator.label, group: indicator.group, indicators: [indicator] });
  }
  return rows;
}

function normalizeCommonFieldChanges(
  changes: Record<string, unknown>,
  indicators: IndicatorMeta[],
): Record<string, unknown> {
  const byColumn = new Map(indicators.map((indicator) => [indicator.column, indicator]));
  return Object.fromEntries(Object.entries(changes).flatMap(([field, value]) => {
    const indicator = byColumn.get(field);
    if (!indicator) return [];
    return [[field, normalizeFieldValue(indicator, value, false)]];
  }));
}

function applyScenarioFieldChanges(
  current: Record<string, unknown>,
  changes: Record<string, unknown>,
  indicators: IndicatorMeta[],
): Record<string, unknown> {
  const result = { ...current };
  const byColumn = new Map(indicators.map((indicator) => [indicator.column, indicator]));
  for (const [field, value] of Object.entries(changes)) {
    const indicator = byColumn.get(field);
    if (!indicator) continue;
    const normalized = normalizeFieldValue(indicator, value, true);
    if (normalized === undefined) delete result[field];
    else result[field] = normalized;
  }
  return result;
}

function normalizeFieldValue(indicator: IndicatorMeta, value: unknown, scenario: boolean): unknown {
  if (indicator.kind === 'yuan' || indicator.kind === 'ratio') {
    if (value === '' || value === null || value === undefined) return scenario ? undefined : null;
    const number = Number(value);
    return Number.isFinite(number) ? number : scenario ? undefined : null;
  }
  if (indicator.kind === 'text') {
    const normalized = String(value || '').trim();
    return normalized || (scenario ? undefined : null);
  }
  if (indicator.kind === 'json' && indicator.multi_value) {
    const normalized = Array.isArray(value) ? value : [];
    return normalized.length || !scenario ? normalized : undefined;
  }
  if (indicator.kind === 'enum') {
    const normalized = String(value || '').trim();
    if (!normalized || (scenario && normalized === 'unknown')) return scenario ? undefined : null;
    return normalized;
  }
  return value;
}

function normalizePendingProposedValue(
  indicator: IndicatorMeta | undefined,
  value: unknown,
): { valid: true; value: unknown } | { valid: false; value?: undefined } {
  if (!indicator || value === undefined || value === null || value === '') return { valid: false };
  if (indicator.kind === 'yuan' || indicator.kind === 'ratio') {
    const numericText = typeof value === 'number' ? String(value) : String(value).trim();
    if (!numericText) return { valid: false };
    const number = Number(numericText);
    return Number.isFinite(number) ? { valid: true, value: number } : { valid: false };
  }
  if (indicator.kind === 'text') {
    const normalized = typeof value === 'string' ? value.trim() : '';
    return normalized ? { valid: true, value: normalized } : { valid: false };
  }
  if (indicator.kind === 'enum') {
    const normalized = typeof value === 'string' ? value.trim() : '';
    return indicator.enum_options.some((option) => option.value === normalized)
      ? { valid: true, value: normalized }
      : { valid: false };
  }
  if (indicator.kind === 'json') {
    if (indicator.editor === 'region_multi') {
      const values = Array.isArray(value) ? value : [value];
      const valid = values.length > 0 && values.every(
        (item) => Boolean(item) && typeof item === 'object' && typeof (item as { province?: unknown }).province === 'string' && Boolean((item as { province: string }).province.trim()),
      );
      return valid ? { valid: true, value: values } : { valid: false };
    }
    if (indicator.multi_value) {
      const values = (Array.isArray(value) ? value : [value]).filter(
        (item) => item !== null && item !== undefined && String(item).trim() !== '',
      );
      return values.length ? { valid: true, value: values } : { valid: false };
    }
    return typeof value === 'object' ? { valid: true, value } : { valid: false };
  }
  return { valid: false };
}

function formatConditionRow(
  row: ConditionRowDefinition,
  fields: Record<string, unknown>,
  taxonomy: IndustryOptionsResponse,
): string {
  if (row.key === 'accepted_industries') {
    const pairs = requirementPairs(fields, taxonomy);
    return pairs.length ? pairs.map((pair) => pair.l2 ? `${pair.l1} / ${pair.l2}` : pair.l1).join('、') : '-';
  }
  const indicator = row.indicators[0];
  const value = fields[indicator.column];
  return hasValue(value) ? formatFieldValue(indicator, value) : '-';
}

function EffectBadge({ effect }: { effect: ConditionEffect | 'pending' | null }) {
  // 描述字段没有规则，留空位而不是画一个「无」——那会读成一种规则。
  if (!effect) return <span className="w-16 shrink-0" />;
  const styles = { required: 'bg-red-50 text-red-700', preferred: 'bg-blue-50 text-blue-700', pending: 'bg-amber-100 text-amber-800' };
  const labels = { required: '必须', preferred: '优先', pending: '需要确认' };
  return <span className={`w-16 shrink-0 px-1.5 py-0.5 text-center text-[11px] font-medium ${styles[effect]}`}>{labels[effect]}</span>;
}

function EffectSelect({ value, onChange, label }: { value: ConditionEffect; onChange: (value: ConditionEffect) => void; label?: string }) {
  return <label className="flex items-center gap-1 text-[11px] text-gray-500">{label ? <span>{label}</span> : null}<select value={value} onChange={(event) => onChange(event.target.value as ConditionEffect)} className="border border-gray-200 bg-white px-1.5 py-1 text-[11px]"><option value="required">必须</option><option value="preferred">优先</option></select></label>;
}

function CheckboxOptions({ value, options, onChange }: { value: string[]; options: Array<{ value: string; label: string }>; onChange: (value: string[]) => void }) {
  return <div className="flex min-h-9 flex-wrap gap-2 border border-gray-200 bg-white p-2">{options.map((option) => <label key={option.value} className="inline-flex items-center gap-1 text-xs text-gray-700"><input type="checkbox" checked={value.includes(option.value)} onChange={() => onChange(value.includes(option.value) ? value.filter((item) => item !== option.value) : [...value, option.value])} />{option.label}</label>)}</div>;
}

/** 返回 null 表示这个字段不是条件，只是描述，不参与初筛和排序。 */
function effectiveEffect(indicator: IndicatorMeta, effects: Record<string, ConditionEffect>, value: unknown): ConditionEffect | null {
  if (effects[indicator.column]) return effects[indicator.column];
  if (['requires_relocation', 'requires_return_investment', 'requires_team_retention'].includes(indicator.column)) {
    if (value === 'required' || value === 'preferred') return value;
    return null;
  }
  if (indicator.column === 'region_constraints_json') {
    const regions = regionArray(value);
    return regions.some((item) => item.effect === 'required' || item.effect === 'excluded') ? 'required' : 'preferred';
  }
  return (indicator.default_effect as ConditionEffect | null) || null;
}

/** 是条件才进条件表；描述字段归模块的「其他」区。 */
function isConditionIndicator(indicator: IndicatorMeta): boolean {
  return Boolean(indicator.default_effect) || indicator.effect_editable;
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
function SimpleInput({ label, value, onChange, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; type?: string }) { return <label className="block"><span className="mb-1 block text-xs font-medium text-gray-600">{label}</span><input type={type} className="input" value={value} onChange={(event) => onChange(event.target.value)} /></label>; }
