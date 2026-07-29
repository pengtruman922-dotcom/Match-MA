import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Check,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileSearch,
  Loader2,
  Pencil,
  Search,
  X,
} from 'lucide-react';
import { areaList } from '@vant/area-data';
import { backgroundJobs, fieldSources, indicatorRegistry, meta, profileSections, research, sellerTargets } from '../../lib/api';
import { formatYuan } from '../../lib/format';
import type {
  IndicatorRegistryResponse,
  IndustryOptionsResponse,
  FieldValueSource,
  ProfileSection,
  ProfileSectionsResponse,
  ResearchProposal,
  ResearchReport,
  SellerTarget,
  SellerResearchStatus,
} from '../../types/api';
import { formatListedStatus, formatTransferRatio, getSubjectDisplay } from './presentation';
import { buildInfoGroups, groupFilledCount, type InfoGroup } from './infoGroups';
import ResearchEvidenceDrawer from './ResearchEvidenceDrawer';
import ResearchReportDrawer from './ResearchReportDrawer';

const ACTIVE_RESEARCH_STATES = new Set([
  'research_queued',
  'researching',
  'research_mapping',
]);

function isResearchBusy(target: SellerTarget): boolean {
  return target.information_status === 'researching'
    || ACTIVE_RESEARCH_STATES.has(target.ai_processing_state);
}

function researchButtonLabel(target: SellerTarget): string {
  if (target.ai_processing_state === 'research_queued') return '排队中';
  if (target.ai_processing_state === 'research_mapping') return '整理结果中';
  return '调研中';
}

/**
 * 标的信息：结构化字段和匹配画像放在同一页，按业务大类分组。
 *
 * 拆成两个 tab 时，基本信息缺了 L1/L2、地区、负债率这些筛选真正读取的维度，
 * 而画像六段孤立成页、看不出和字段的关系。合并之后每个大类里
 * 「硬数据 + 装不下的定性判断」是并排的，字段上的「筛」角标进一步告诉顾问
 * 哪些空缺补了会改变召回。
 */
export default function TargetInfoPanel({
  target,
  onTargetChanged,
}: {
  target: SellerTarget;
  onTargetChanged?: (target: SellerTarget) => void;
}) {
  const [currentTarget, setCurrentTarget] = useState(target);
  const [data, setData] = useState<ProfileSectionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [researching, setResearching] = useState(false);
  const [researchJobId, setResearchJobId] = useState<string | null>(null);
  const [proposals, setProposals] = useState<ResearchProposal[]>([]);
  const [reviewingProposalId, setReviewingProposalId] = useState<string | null>(null);
  const [showResearchConflicts, setShowResearchConflicts] = useState(false);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [registry, setRegistry] = useState<IndicatorRegistryResponse | null>(null);
  const [sources, setSources] = useState<FieldValueSource[]>([]);
  const [selectedEvidence, setSelectedEvidence] = useState<FieldValueSource | null>(null);
  const [latestResearchJob, setLatestResearchJob] = useState<SellerResearchStatus['latest_job']>(null);
  const [researchReport, setResearchReport] = useState<ResearchReport | null>(null);
  const [industryOptions, setIndustryOptions] = useState<IndustryOptionsResponse>({ l1: [], l2: [] });
  const researchBusy = researching || isResearchBusy(currentTarget);

  const groups = useMemo(
    () =>
      registry
        ? buildInfoGroups(currentTarget, registry, {
            formatYuan: (value) => formatYuan(value as string),
            formatListedStatus,
            formatTransferRatio,
            getSubjectDisplay,
          })
        : [],
    [currentTarget, registry],
  );
  const conflictProposals = useMemo(
    () => proposals.filter((item) => item.conflict_kind === 'same_period_conflict'),
    [proposals],
  );
  const otherPendingProposals = useMemo(
    () => proposals.filter((item) => item.conflict_kind !== 'same_period_conflict'),
    [proposals],
  );

  useEffect(() => setCurrentTarget(target), [target]);

  const load = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      const [freshTarget, profileData, proposalData, registryData, sourceData, industryData, researchStatus] = await Promise.all([
        sellerTargets.get(currentTarget.id),
        profileSections.list('seller_target', currentTarget.id),
        research.proposals(currentTarget.id, 'pending_review'),
        indicatorRegistry.list('seller_target'),
        fieldSources.list({ entity_type: 'seller_target', entity_id: currentTarget.id, limit: 200 }),
        meta.industryOptions(),
        research.sellerTargetStatus(currentTarget.id),
      ]);
      setCurrentTarget(freshTarget);
      onTargetChanged?.(freshTarget);
      setData(profileData);
      setProposals(proposalData.filter((item) => item.proposed_value_json.info_status !== 'not_found'));
      setRegistry(registryData);
      setSources(sourceData);
      setIndustryOptions(industryData);
      setLatestResearchJob(researchStatus.latest_job);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载标的信息失败');
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [currentTarget.id, onTargetChanged]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!researchJobId) return;
    const timer = window.setInterval(() => {
      void backgroundJobs
        .get(researchJobId)
        .then((job) => {
          if (['succeeded', 'failed', 'canceled'].includes(job.status)) {
            window.clearInterval(timer);
            setResearchJobId(null);
            setResearching(false);
            if (job.status === 'failed') setError(job.error_message || '调研任务失败');
            void load();
          }
        })
        .catch((err) => {
          window.clearInterval(timer);
          setResearchJobId(null);
          setResearching(false);
          setError(err instanceof Error ? err.message : '读取调研任务失败');
        });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [load, researchJobId]);

  // 调研可能从列表页或另一个浏览器标签发起，不能只依赖本页面保存的 job id。
  const refreshResearchState = useCallback(async () => {
    try {
      const freshTarget = await sellerTargets.get(currentTarget.id);
      setCurrentTarget(freshTarget);
      onTargetChanged?.(freshTarget);
      if (researchBusy && !isResearchBusy(freshTarget)) {
        setResearching(false);
        setResearchJobId(null);
        await load(false);
      }
    } catch {
      // 短暂网络失败不应重新启用按钮；下一轮或下一次聚焦继续同步。
    }
  }, [currentTarget.id, load, onTargetChanged, researchBusy]);

  // 活跃期间每 4 秒同步排队/运行/整理阶段。
  useEffect(() => {
    if (!researchBusy) return;
    const timer = window.setInterval(() => void refreshResearchState(), 4000);
    return () => window.clearInterval(timer);
  }, [refreshResearchState, researchBusy]);

  // 即使当前页面看起来空闲，重新聚焦也要检查是否从别处发起了任务。
  useEffect(() => {
    const onFocus = () => void refreshResearchState();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [refreshResearchState]);

  const sectionByCode = new Map<string, ProfileSection>();
  for (const section of data?.sections || []) {
    if (!sectionByCode.has(section.section_code)) sectionByCode.set(section.section_code, section);
  }
  const sourceByField = new Map<string, FieldValueSource>();
  for (const source of sources) {
    if (!sourceByField.has(source.field_path)) sourceByField.set(source.field_path, source);
  }

  const save = async (code: string) => {
    setSaving(true);
    try {
      await profileSections.write('seller_target', currentTarget.id, {
        section_code: code,
        info_status: 'filled',
        content_text: draft.trim() || null,
      });
      setEditing(null);
      setDraft('');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const saveFields = async (changes: Record<string, unknown>) => {
    setSaving(true);
    try {
      const updated = await sellerTargets.updateFields(currentTarget.id, changes);
      setCurrentTarget(updated);
      setEditing(null);
      setDraft('');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存字段失败');
    } finally {
      setSaving(false);
    }
  };

  const saveField = (field: string, value: unknown) => saveFields({ [field]: value });

  const startResearch = async () => {
    setResearching(true);
    setError(null);
    try {
      const job = await research.startSellerTarget(currentTarget.id);
      setResearchJobId(job.job_id);
    } catch (err) {
      setResearching(false);
      setError(err instanceof Error ? err.message : '启动调研失败');
    }
  };

  const reviewProposal = async (proposalId: string, decision: 'accept' | 'reject') => {
    setReviewingProposalId(proposalId);
    try {
      if (decision === 'accept') await research.acceptProposal(proposalId);
      else await research.rejectProposal(proposalId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : '处理调研建议失败');
    } finally {
      setReviewingProposalId(null);
    }
  };

  const openResearchReport = async (jobId: string) => {
    try {
      setResearchReport(await research.report(jobId));
      setSelectedEvidence(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取调研报告失败');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-1 py-3 text-xs text-gray-400">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        加载标的信息…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 pb-3">
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span className="inline-flex items-center gap-1">
            <span className="inline-block bg-brand-50 px-1 py-0.5 text-[10px] font-medium text-brand-700">筛</span>
            参与筛选与打分
          </span>
          {currentTarget.last_research_at && (
            <span>上次调研：{currentTarget.last_research_at.slice(0, 10)}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {Boolean(latestResearchJob?.result_json?.report_text) && latestResearchJob && (
            <button
              type="button"
              onClick={() => void openResearchReport(latestResearchJob.id)}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-xs text-gray-500 hover:bg-gray-50 hover:text-brand-700"
            >
              <FileSearch className="h-3 w-3" />查看调研报告
            </button>
          )}
          <button
            type="button"
            disabled={researchBusy}
            onClick={() => void startResearch()}
            title={researchBusy ? '该标的已有调研任务在排队或执行中，请等待完成' : '发起 AI 调研'}
            className="inline-flex cursor-pointer items-center gap-1 border border-brand-200 px-2.5 py-1 text-xs text-brand-700 disabled:cursor-not-allowed disabled:border-gray-200 disabled:bg-gray-100 disabled:text-gray-400 disabled:opacity-100"
          >
            {researchBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Search className="h-3 w-3" />}
            {researchBusy ? researchButtonLabel(currentTarget) : 'AI调研'}
          </button>
        </div>
      </div>

      {error && <p className="border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p>}
      {!error && currentTarget.ai_processing_state === 'research_failed' && (
        <p className="border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
          {currentTarget.ai_processing_detail}
        </p>
      )}

      {conflictProposals.length > 0 && (
        <div className="border border-amber-100 bg-amber-50/50 px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-xs font-medium text-amber-800">调研发现 {conflictProposals.length} 个与当前信息冲突的字段</p>
              <p className="mt-1 text-xs text-amber-700">系统没有自动覆盖，请集中核对后再决定是否采纳。</p>
            </div>
            <button
              type="button"
              onClick={() => setShowResearchConflicts((value) => !value)}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs text-amber-800 hover:bg-amber-100"
            >
              {showResearchConflicts ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              {showResearchConflicts ? '收起冲突' : '查看冲突'}
            </button>
          </div>
          {showResearchConflicts ? (
            <div className="mt-2 space-y-2">
              {conflictProposals.map((proposal) => (
                <ProposalCard
                  key={proposal.id}
                  proposal={proposal}
                  busy={reviewingProposalId === proposal.id}
                  onReview={reviewProposal}
                />
              ))}
            </div>
          ) : null}
        </div>
      )}

      {otherPendingProposals.length > 0 && (
        <div className="border border-amber-100 bg-amber-50/50 px-4 py-3">
          <p className="text-xs font-medium text-amber-800">待确认调研建议（{otherPendingProposals.length}）</p>
          <p className="mt-1 text-xs text-amber-700">这些是旧批次或非冲突建议，新调研的可追溯补充信息会自动写入。</p>
          <div className="mt-2 space-y-2">
            {otherPendingProposals.map((proposal) => (
              <ProposalCard
                key={proposal.id}
                proposal={proposal}
                busy={reviewingProposalId === proposal.id}
                onReview={reviewProposal}
              />
            ))}
          </div>
        </div>
      )}

      {groups.map((group) => {
        const section = group.sectionCode ? sectionByCode.get(group.sectionCode) : undefined;
        const filled = groupFilledCount(group);
        const isEmpty = filled === 0 && !section;
        // 整组全空的默认折叠：信息页有 50+ 字段，全展开会把有内容的部分淹掉。
        const isCollapsed = collapsed[group.key] ?? isEmpty;
        return (
          <section key={group.key} className="border border-gray-200 bg-white">
            <button
              type="button"
              onClick={() => setCollapsed((prev) => ({ ...prev, [group.key]: !isCollapsed }))}
              className="flex w-full items-center justify-between px-4 py-2.5 text-left hover:bg-gray-50"
            >
              <span className="flex items-center gap-2 text-sm font-medium text-gray-900">
                {isCollapsed ? (
                  <ChevronRight className="h-4 w-4 text-gray-400" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-gray-400" />
                )}
                {group.label}
              </span>
              <span className="text-xs text-gray-400">
                {group.fields.length > 0 && `${filled}/${group.fields.length} 字段`}
                {group.sectionCode && ' · 含其他补充栏'}
              </span>
            </button>
            {!isCollapsed && (
              <div className="border-t border-gray-100 px-4 py-3">
                {group.fields.length > 0 && (
                  <div className="grid grid-cols-1 gap-x-8 gap-y-2 sm:grid-cols-2">
                    {group.fields.map((field) => {
                      const shared = {
                        field,
                        editing: editing === `field:${field.field}`,
                        saving,
                        source: sourceByField.get(field.field),
                        onShowEvidence: (source: FieldValueSource) => setSelectedEvidence(source),
                        onStart: () => { setEditing(`field:${field.field}`); setDraft(String((currentTarget as unknown as Record<string, unknown>)[field.field] ?? '')); },
                        onCancel: () => setEditing(null),
                      };
                      if (field.field === 'industry_pairs_json') {
                        return <IndustryPairsField key={field.field} {...shared} pairs={currentTarget.industry_pairs_json || []} options={industryOptions} onSave={(value) => saveField(field.field, value)} />;
                      }
                      if (field.field === 'location_province') {
                        return <LocationField key={field.field} {...shared} target={currentTarget} onSave={saveFields} />;
                      }
                      return <StructuredField
                        key={field.field} {...shared} draft={draft}
                        onDraft={setDraft} onSave={(value) => saveField(field.field, value)}
                      />;
                    })}
                  </div>
                )}
                {group.sectionCode && (
                  <ProfileBlock
                    code={group.sectionCode}
                    section={section}
                    hasFields={group.fields.length > 0}
                    editing={editing === group.sectionCode}
                    draft={draft}
                    saving={saving}
                    onDraft={setDraft}
                    onStartEdit={() => {
                      setEditing(group.sectionCode);
                      setDraft(section?.content_text || '');
                    }}
                    onCancel={() => setEditing(null)}
                    onSave={save}
                  />
                )}
              </div>
            )}
          </section>
        );
      })}
      {selectedEvidence && (
        <ResearchEvidenceDrawer
          source={selectedEvidence}
          onClose={() => setSelectedEvidence(null)}
          onOpenReport={(jobId) => void openResearchReport(jobId)}
        />
      )}
      {researchReport && <ResearchReportDrawer report={researchReport} onClose={() => setResearchReport(null)} />}
    </div>
  );
}

function StructuredField({ field, editing, draft, saving, source, onStart, onCancel, onDraft, onSave, onShowEvidence }: {
  field: InfoGroup['fields'][number]; editing: boolean; draft: string; saving: boolean;
  source?: FieldValueSource;
  onStart: () => void; onCancel: () => void; onDraft: (value: string) => void; onSave: (value: unknown) => Promise<void>;
  onShowEvidence: (source: FieldValueSource) => void;
}) {
  const raw = draft.trim();
  const save = () => {
    if (field.kind === 'enum') return onSave(raw || null);
    if (field.kind === 'yuan' || field.kind === 'ratio') return onSave(raw ? Number(raw) : null);
    return onSave(raw || null);
  };
  return <div className="flex items-start gap-2">
    <span className="flex w-28 shrink-0 items-center gap-1 pt-1 text-xs text-gray-500">{field.label}{field.screening && <span title="参与筛选与打分" className="bg-brand-50 px-1 text-[10px] font-medium text-brand-700">筛</span>}</span>
    <div className="min-w-0 flex-1">
      {editing ? <div className="flex gap-1">
        {field.kind === 'enum' ? <select value={raw} onChange={(event) => onDraft(event.target.value)} className="min-w-0 flex-1 border border-gray-200 px-1 text-xs">{field.enumOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
          : <input type={field.kind === 'yuan' || field.kind === 'ratio' ? 'number' : 'text'} value={draft} onChange={(event) => onDraft(event.target.value)} className="min-w-0 flex-1 border border-gray-200 px-1 text-xs" />}
        <button type="button" disabled={saving} onClick={() => void save()} className="text-brand-600"><Check className="h-3.5 w-3.5" /></button><button type="button" onClick={onCancel} className="text-gray-400"><X className="h-3.5 w-3.5" /></button>
      </div> : <button type="button" disabled={!field.writable} onClick={onStart} className={`group flex w-full items-center justify-between text-left text-sm ${field.value ? 'text-gray-800' : 'text-gray-300'} ${field.writable ? 'hover:text-brand-600' : ''}`}><span>{field.value || '-'}</span>{field.writable && <Pencil className="h-3 w-3 opacity-0 group-hover:opacity-100" />}</button>}
      {!editing && <FieldCaption source={source} onShowEvidence={onShowEvidence} />}
    </div>
  </div>;
}

type SpecialFieldProps = {
  field: InfoGroup['fields'][number];
  editing: boolean;
  saving: boolean;
  source?: FieldValueSource;
  onStart: () => void;
  onCancel: () => void;
  onShowEvidence: (source: FieldValueSource) => void;
};

function FieldCaption({ source, onShowEvidence }: { source?: FieldValueSource; onShowEvidence: (source: FieldValueSource) => void }) {
  if (!source) return null;
  const detail = <>{fieldSourceLabel(source)}{source.created_by_name && ` · ${source.created_by_name}`}{source.created_at && ` · ${formatSourceTime(source.created_at)}`}</>;
  if (source.source_type === 'research_proposal') {
    return <button type="button" onClick={() => onShowEvidence(source)} className="mt-0.5 block text-left text-[10px] text-gray-400 hover:text-brand-600 hover:underline">来源：{detail}</button>;
  }
  return <p className="mt-0.5 text-[10px] text-gray-400">来源：{detail}</p>;
}

function FieldLabel({ field }: { field: InfoGroup['fields'][number] }) {
  return <span className="flex w-28 shrink-0 items-center gap-1 pt-1 text-xs text-gray-500">{field.label}{field.screening && <span title="参与筛选与打分" className="bg-brand-50 px-1 text-[10px] font-medium text-brand-700">筛</span>}</span>;
}

function IndustryPairsField({ field, editing, saving, source, onStart, onCancel, onShowEvidence, pairs, options, onSave }: SpecialFieldProps & {
  pairs: Array<{ l1: string; l2?: string }>;
  options: IndustryOptionsResponse;
  onSave: (value: Array<{ l1: string; l2?: string }>) => Promise<void>;
}) {
  const [draftPairs, setDraftPairs] = useState<Array<{ l1: string; l2?: string }>>(pairs);
  const [l1Query, setL1Query] = useState('');
  const [l2Query, setL2Query] = useState('');
  const [l2Scope, setL2Scope] = useState('selected');

  useEffect(() => {
    if (editing) {
      setDraftPairs(pairs);
      setL1Query('');
      setL2Query('');
      setL2Scope('selected');
    }
  }, [editing, pairs]);

  const selectedL1 = [...new Set(draftPairs.map((pair) => pair.l1))];
  const visibleL1 = options.l1.filter(({ term }) => term.includes(l1Query.trim()));
  const scopedL2 = options.l2.filter(({ l1, term }) => {
    const inScope = l2Scope === 'all' || (l2Scope === 'selected' ? selectedL1.includes(l1) : l1 === l2Scope);
    return inScope && term.includes(l2Query.trim());
  });
  const toggleL1 = (l1: string) => setDraftPairs((current) => (
    current.some((pair) => pair.l1 === l1)
      ? current.filter((pair) => pair.l1 !== l1)
      : [...current, { l1 }]
  ));
  const toggleL2 = (l1: string, l2: string) => setDraftPairs((current) => (
    current.some((pair) => pair.l1 === l1 && pair.l2 === l2)
      ? current.filter((pair) => !(pair.l1 === l1 && pair.l2 === l2))
      : [...current, { l1, l2 }]
  ));
  const display = pairs.map((pair) => [pair.l1, pair.l2].filter(Boolean).join(' / ')).join('；');

  return <div className="flex items-start gap-2 sm:col-span-2">
    <FieldLabel field={field} />
    <div className="min-w-0 flex-1">
      {editing ? <div className="space-y-2 border border-gray-200 bg-gray-50 p-2">
        <div>
          <div className="mb-1 flex items-center gap-2 text-xs text-gray-600"><span className="font-medium">一级行业（可多选）</span><input value={l1Query} onChange={(event) => setL1Query(event.target.value)} placeholder="搜索" className="min-w-0 border border-gray-200 bg-white px-1.5 py-0.5 text-xs" /></div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 sm:grid-cols-3">
            {visibleL1.map(({ term }) => <label key={term} className="flex min-w-0 items-center gap-1 text-xs text-gray-700"><input type="checkbox" checked={selectedL1.includes(term)} onChange={() => toggleL1(term)} /> <span className="truncate">{term}</span></label>)}
          </div>
        </div>
        <div className="border-t border-gray-200 pt-2">
          <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-gray-600"><span className="font-medium">二级行业（可多选）</span><select value={l2Scope} onChange={(event) => setL2Scope(event.target.value)} className="border border-gray-200 bg-white px-1 py-0.5 text-xs"><option value="selected">已选一级行业</option><option value="all">全部一级行业</option>{selectedL1.map((l1) => <option key={l1} value={l1}>{l1}</option>)}</select><input value={l2Query} onChange={(event) => setL2Query(event.target.value)} placeholder="搜索" className="min-w-0 border border-gray-200 bg-white px-1.5 py-0.5 text-xs" /></div>
          {selectedL1.length === 0 && l2Scope === 'selected' ? <p className="text-xs text-gray-400">先选择一级行业，或切换为“全部一级行业”。</p> : <div className="max-h-32 overflow-y-auto space-y-1"><div className="grid grid-cols-1 gap-x-3 gap-y-1 sm:grid-cols-2">{scopedL2.map(({ term, l1 }) => <label key={`${l1}:${term}`} className="flex min-w-0 items-center gap-1 text-xs text-gray-700"><input type="checkbox" checked={draftPairs.some((pair) => pair.l1 === l1 && pair.l2 === term)} onChange={() => toggleL2(l1, term)} /> <span className="truncate">{term}</span><span className="ml-auto shrink-0 text-[10px] text-gray-400">{l1}</span></label>)}</div></div>}
        </div>
        <div className="flex items-center gap-2"><button type="button" disabled={saving} onClick={() => void onSave(draftPairs)} className="inline-flex items-center gap-1 bg-brand-600 px-2.5 py-1 text-xs text-white disabled:opacity-40"><Check className="h-3 w-3" />保存</button><button type="button" onClick={onCancel} className="text-xs text-gray-400 hover:text-gray-600">取消</button></div>
      </div> : <><button type="button" disabled={!field.writable} onClick={onStart} className={`group flex w-full items-center justify-between text-left text-sm ${display ? 'text-gray-800' : 'text-gray-300'} ${field.writable ? 'hover:text-brand-600' : ''}`}><span>{display || '-'}</span>{field.writable && <Pencil className="h-3 w-3 opacity-0 group-hover:opacity-100" />}</button><FieldCaption source={source} onShowEvidence={onShowEvidence} /></>}
    </div>
  </div>;
}

const areaEntries = {
  province: Object.entries(areaList.province_list),
  city: Object.entries(areaList.city_list),
  district: Object.entries(areaList.county_list),
};

function areaCode(entries: Array<[string, string]>, name: string | null): string {
  return entries.find(([, label]) => label === name)?.[0] || '';
}

function LocationField({ field, editing, saving, source, onStart, onCancel, onShowEvidence, target, onSave }: SpecialFieldProps & {
  target: SellerTarget;
  onSave: (changes: Record<string, unknown>) => Promise<void>;
}) {
  const [province, setProvince] = useState(target.location_province || '');
  const [city, setCity] = useState(target.location_city || '');
  const [district, setDistrict] = useState(target.location_district || '');
  const provinceCode = areaCode(areaEntries.province, province);
  const cityCode = areaCode(areaEntries.city, city);
  const cityOptions = areaEntries.city.filter(([code]) => !provinceCode || code.slice(0, 2) === provinceCode.slice(0, 2));
  const districtOptions = areaEntries.district.filter(([code]) => !cityCode || code.slice(0, 4) === cityCode.slice(0, 4));

  useEffect(() => {
    if (editing) {
      setProvince(target.location_province || '');
      setCity(target.location_city || '');
      setDistrict(target.location_district || '');
    }
  }, [editing, target.location_city, target.location_district, target.location_province]);

  const display = [target.location_province, target.location_city, target.location_district].filter(Boolean).join(' / ');
  return <div className="flex items-start gap-2">
    <FieldLabel field={field} />
    <div className="min-w-0 flex-1">
      {editing ? <div className="space-y-2 border border-gray-200 bg-gray-50 p-2"><div className="grid grid-cols-1 gap-1 sm:grid-cols-3"><select value={province} onChange={(event) => { setProvince(event.target.value); setCity(''); setDistrict(''); }} className="border border-gray-200 bg-white px-1.5 py-1 text-xs"><option value="">省（可不填）</option>{areaEntries.province.map(([code, name]) => <option key={code} value={name}>{name}</option>)}</select><select value={city} onChange={(event) => { setCity(event.target.value); setDistrict(''); }} disabled={!province} className="border border-gray-200 bg-white px-1.5 py-1 text-xs disabled:bg-gray-100"><option value="">市（可不填）</option>{cityOptions.map(([code, name]) => <option key={code} value={name}>{name}</option>)}</select><select value={district} onChange={(event) => setDistrict(event.target.value)} disabled={!city} className="border border-gray-200 bg-white px-1.5 py-1 text-xs disabled:bg-gray-100"><option value="">区/县（可不填）</option>{districtOptions.map(([code, name]) => <option key={code} value={name}>{name}</option>)}</select></div><p className="text-[10px] text-gray-400">变更上级会自动清空下级；筛选仍按省、市、区三个字段命中。</p><div className="flex items-center gap-2"><button type="button" disabled={saving} onClick={() => void onSave({ location_province: province || null, location_city: city || null, location_district: district || null })} className="inline-flex items-center gap-1 bg-brand-600 px-2.5 py-1 text-xs text-white disabled:opacity-40"><Check className="h-3 w-3" />保存</button><button type="button" onClick={onCancel} className="text-xs text-gray-400 hover:text-gray-600">取消</button></div></div> : <><button type="button" disabled={!field.writable} onClick={onStart} className={`group flex w-full items-center justify-between text-left text-sm ${display ? 'text-gray-800' : 'text-gray-300'} ${field.writable ? 'hover:text-brand-600' : ''}`}><span>{display || '-'}</span>{field.writable && <Pencil className="h-3 w-3 opacity-0 group-hover:opacity-100" />}</button><FieldCaption source={source} onShowEvidence={onShowEvidence} /></>}
    </div>
  </div>;
}

function fieldSourceLabel(source: FieldValueSource): string {
  if (['direct_api', 'manual', 'manual_edit'].includes(source.source_type || '')) return '手动编辑';
  if (source.source_type === 'research_proposal') return 'AI调研';
  if (['update_log_rollback', 'rollback'].includes(source.source_type || '')) return '更新回滚';
  if (source.evidence_span?.attachment_id) return '文字+附件更新';
  return '文字更新';
}

function ProfileBlock({
  code,
  section,
  hasFields,
  editing,
  draft,
  saving,
  onDraft,
  onStartEdit,
  onCancel,
  onSave,
}: {
  code: string;
  section: ProfileSection | undefined;
  hasFields: boolean;
  editing: boolean;
  draft: string;
  saving: boolean;
  onDraft: (value: string) => void;
  onStartEdit: () => void;
  onCancel: () => void;
  onSave: (code: string) => Promise<void>;
}) {
  return (
    <div className={hasFields ? 'mt-3 border-t border-dashed border-gray-100 pt-3' : ''}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-gray-500">其他</span>
        {!editing && (
          <button
            type="button"
            onClick={onStartEdit}
            className="inline-flex items-center gap-1 text-xs text-brand-600 hover:underline"
          >
            <Pencil className="h-3 w-3" />
            {section ? '编辑' : '填写'}
          </button>
        )}
      </div>
      {editing ? (
        <div className="mt-1.5 space-y-1.5">
          <textarea
            value={draft}
            onChange={(event) => onDraft(event.target.value)}
            rows={3}
            className="w-full border border-gray-200 px-2 py-1.5 text-xs outline-none focus:border-brand-600"
            placeholder="只写结构化字段装不下的定性判断，财务数字留在字段里"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={saving}
              onClick={() => void onSave(code)}
              className="inline-flex items-center gap-1 bg-brand-600 px-2.5 py-1 text-xs text-white disabled:opacity-40"
            >
              <Check className="h-3 w-3" />
              保存
            </button>
            <button type="button" onClick={onCancel} className="text-xs text-gray-400 hover:text-gray-600">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      ) : (
        <>
          <p className={`mt-0.5 text-xs ${section ? 'text-gray-600' : 'text-gray-300'}`}>
            {section?.content_text || '-'}
          </p>
          {section && (section.source_title || section.source_type) && (
            <p className="mt-1 text-[11px] text-gray-400">
              来源：
              {section.source_url ? (
                <a
                  href={section.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="hover:text-brand-600 hover:underline"
                >
                  {profileSourceLabel(section.source_type)}
                </a>
              ) : (
                profileSourceLabel(section.source_type)
              )}
              {section.as_of_date && ` · 截至 ${section.as_of_date}`}
              {section.updated_by_name && ` · ${section.updated_by_name}`}
              {section.updated_at && ` · ${formatSourceTime(section.updated_at)}`}
            </p>
          )}
        </>
      )}
    </div>
  );
}

function profileSourceLabel(sourceType: string | null): string {
  if (['manual_edit', 'manual', 'direct_api'].includes(sourceType || '')) return '手动编辑';
  if (sourceType === 'research_proposal') return 'AI调研';
  if (['rollback', 'update_log_rollback'].includes(sourceType || '')) return '更新回滚';
  return '文字更新';
}

function ProposalCard({
  proposal,
  busy,
  onReview,
}: {
  proposal: ResearchProposal;
  busy: boolean;
  onReview: (proposalId: string, decision: 'accept' | 'reject') => Promise<void>;
}) {
  // 调研查过但没有公开信息时提议 not_found —— 内容为空是正常的，
  // 它提议的是「确认这一栏是缺口」而不是一段描述。
  const proposed =
    proposal.proposal_kind !== 'profile_section'
      ? String(proposal.proposed_value_json.value || '')
      : proposal.proposed_value_json.info_status === 'not_found'
        ? '公开渠道未找到相关信息，建议标记为暂无信息'
        : String(proposal.proposed_value_json.content_text || '');
  const sources = Array.isArray(proposal.proposed_value_json.sources)
    ? (proposal.proposed_value_json.sources as string[])
    : proposal.source_url
      ? [proposal.source_url]
      : [];
  const actionable = proposal.is_actionable !== false && !proposal.validation_error;

  return (
    <div className="border border-amber-100 bg-white px-3 py-2 text-xs">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium text-gray-700">
            {proposal.section_label || proposal.field_path}
            <span className="ml-2 font-normal text-amber-700">{conflictLabel(proposal.conflict_kind)}</span>
          </p>
          <p className="mt-1 text-gray-600">{proposed}</p>
          {!actionable && (
            <p className="mt-1 text-red-600">格式无效：{proposal.validation_error || '该建议无法写入，只能忽略'}</p>
          )}
          {sources.map((url) => (
            <a
              key={url}
              href={url}
              target="_blank"
              rel="noreferrer"
              className="mt-1 flex items-center gap-1 text-brand-600 hover:underline"
            >
              <ExternalLink className="h-3 w-3 shrink-0" />
              <span className="truncate">{sourceDomain(url)}</span>
            </a>
          ))}
        </div>
        <div className="flex shrink-0 gap-1.5">
          {actionable && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void onReview(proposal.id, 'accept')}
              className="bg-brand-600 px-2 py-1 text-white disabled:opacity-50"
            >
              确认
            </button>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={() => void onReview(proposal.id, 'reject')}
            className="border border-gray-200 px-2 py-1 text-gray-500 disabled:opacity-50"
          >
            忽略
          </button>
        </div>
      </div>
    </div>
  );
}

function sourceDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

function formatSourceTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function conflictLabel(kind: ResearchProposal['conflict_kind']): string {
  return {
    consistent: '与现有信息一致',
    supplement: '补充信息',
    temporal_update: '新期间信息',
    same_period_conflict: '与当前信息冲突',
  }[kind];
}

export type { InfoGroup };
