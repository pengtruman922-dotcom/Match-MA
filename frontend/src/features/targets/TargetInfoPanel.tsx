import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Check,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Loader2,
  Pencil,
  Search,
  X,
} from 'lucide-react';
import { backgroundJobs, fieldSources, indicatorRegistry, profileSections, research, sellerTargets } from '../../lib/api';
import { formatYuan } from '../../lib/format';
import { sourceTypeLabel } from '../../lib/fieldLabels';
import type {
  IndicatorRegistryResponse,
  FieldValueSource,
  ProfileSection,
  ProfileSectionsResponse,
  ResearchProposal,
  SellerTarget,
} from '../../types/api';
import { formatListedStatus, formatTransferRatio, getSubjectDisplay } from './presentation';
import { buildInfoGroups, groupFilledCount, type InfoGroup } from './infoGroups';

/**
 * 标的信息：结构化字段和匹配画像放在同一页，按业务大类分组。
 *
 * 拆成两个 tab 时，基本信息缺了 L1/L2、地区、负债率这些筛选真正读取的维度，
 * 而画像六段孤立成页、看不出和字段的关系。合并之后每个大类里
 * 「硬数据 + 装不下的定性判断」是并排的，字段上的「筛」角标进一步告诉顾问
 * 哪些空缺补了会改变召回。
 */
export default function TargetInfoPanel({ target }: { target: SellerTarget }) {
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
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [registry, setRegistry] = useState<IndicatorRegistryResponse | null>(null);
  const [sources, setSources] = useState<FieldValueSource[]>([]);

  const groups = useMemo(
    () =>
      registry
        ? buildInfoGroups(target, registry, {
            formatYuan: (value) => formatYuan(value as string),
            formatListedStatus,
            formatTransferRatio,
            getSubjectDisplay,
          })
        : [],
    [currentTarget, registry],
  );

  useEffect(() => setCurrentTarget(target), [target]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [profileData, proposalData, registryData, sourceData] = await Promise.all([
        profileSections.list('seller_target', currentTarget.id),
        research.proposals(currentTarget.id, 'pending_review'),
        indicatorRegistry.list('seller_target'),
        fieldSources.list({ entity_type: 'seller_target', entity_id: currentTarget.id, limit: 200 }),
      ]);
      setData(profileData);
      setProposals(proposalData);
      setRegistry(registryData);
      setSources(sourceData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载标的信息失败');
    } finally {
      setLoading(false);
    }
  }, [currentTarget.id]);

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

  const saveField = async (field: string, value: unknown) => {
    setSaving(true);
    try {
      const updated = await sellerTargets.updateFields(currentTarget.id, { [field]: value });
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
        <button
          type="button"
          disabled={researching}
          onClick={() => void startResearch()}
          className="inline-flex items-center gap-1 border border-brand-200 px-2.5 py-1 text-xs text-brand-700 disabled:opacity-50"
        >
          {researching ? <Loader2 className="h-3 w-3 animate-spin" /> : <Search className="h-3 w-3" />}
          {researching ? '调研中' : '公开信息调研'}
        </button>
      </div>

      {error && <p className="border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p>}

      {proposals.length > 0 && (
        <div className="border border-amber-100 bg-amber-50/50 px-4 py-3">
          <p className="text-xs font-medium text-amber-800">待确认调研建议（{proposals.length}）</p>
          <div className="mt-2 space-y-2">
            {proposals.map((proposal) => (
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
                    {group.fields.map((field) => <StructuredField
                      key={field.field} field={field} editing={editing === `field:${field.field}`} draft={draft} saving={saving}
                      source={sourceByField.get(field.field)}
                      onStart={() => { setEditing(`field:${field.field}`); setDraft(String((currentTarget as unknown as Record<string, unknown>)[field.field] ?? '')); }}
                      onCancel={() => setEditing(null)} onDraft={setDraft} onSave={(value) => saveField(field.field, value)}
                    />)}
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
    </div>
  );
}

function StructuredField({ field, editing, draft, saving, source, onStart, onCancel, onDraft, onSave }: {
  field: InfoGroup['fields'][number]; editing: boolean; draft: string; saving: boolean;
  source?: FieldValueSource;
  onStart: () => void; onCancel: () => void; onDraft: (value: string) => void; onSave: (value: unknown) => Promise<void>;
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
      {!editing && source && <p className="mt-0.5 text-[10px] text-gray-400">来源：{source.source_label || source.source_type || '-'}{source.created_by_name && ` · ${source.created_by_name}`}{source.created_at && ` · ${formatSourceTime(source.created_at)}`}</p>}
    </div>
  </div>;
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
                  {section.source_title || sourceTypeLabel(section.source_type)}
                </a>
              ) : (
                section.source_title || sourceTypeLabel(section.source_type)
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

  return (
    <div className="border border-amber-100 bg-white px-3 py-2 text-xs">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium text-gray-700">
            {proposal.section_label || proposal.field_path}
            <span className="ml-2 font-normal text-amber-700">{conflictLabel(proposal.conflict_kind)}</span>
          </p>
          <p className="mt-1 text-gray-600">{proposed}</p>
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
          <button
            type="button"
            disabled={busy}
            onClick={() => void onReview(proposal.id, 'accept')}
            className="bg-brand-600 px-2 py-1 text-white disabled:opacity-50"
          >
            确认
          </button>
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
