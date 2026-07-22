import { useCallback, useEffect, useState } from 'react';
import { Check, ExternalLink, Loader2, Pencil, Search, X } from 'lucide-react';
import { backgroundJobs, profileSections, research } from '../../lib/api';
import { fieldLabel, sourceTypeLabel } from '../../lib/fieldLabels';
import type { ProfileSection, ProfileSectionsResponse, ResearchProposal } from '../../types/api';

const STATUS_LABELS: Record<ProfileSection['info_status'], string> = {
  filled: '已填写',
  not_found: '暂无信息',
  not_applicable: '不适用',
};

/**
 * 匹配画像：深评真正读的那一层。结构化字段答不了"是不是链主、团队怎么样"，
 * 这六栏就是给这类判断准备的，未填的栏目同时是调研任务清单。
 */
export default function ProfileSectionsPanel({
  entityType,
  entityId,
}: {
  entityType: 'seller_target' | 'buyer_intent';
  entityId: string;
}) {
  const [data, setData] = useState<ProfileSectionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [researching, setResearching] = useState(false);
  const [researchJobId, setResearchJobId] = useState<string | null>(null);
  const [proposals, setProposals] = useState<ResearchProposal[]>([]);
  const [reviewingProposalId, setReviewingProposalId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [profileData, proposalData] = await Promise.all([
        profileSections.list(entityType, entityId),
        entityType === 'seller_target' ? research.proposals(entityId, 'pending_review') : Promise.resolve([]),
      ]);
      setData(profileData);
      setProposals(proposalData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载画像失败');
    } finally {
      setLoading(false);
    }
  }, [entityType, entityId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!researchJobId) return;
    const timer = window.setInterval(() => {
      void backgroundJobs.get(researchJobId).then((job) => {
        if (['succeeded', 'failed', 'canceled'].includes(job.status)) {
          window.clearInterval(timer);
          setResearchJobId(null);
          setResearching(false);
          if (job.status === 'failed') setError(job.error_message || '调研任务失败');
          void load();
        }
      }).catch((err) => {
        window.clearInterval(timer);
        setResearchJobId(null);
        setResearching(false);
        setError(err instanceof Error ? err.message : '读取调研任务失败');
      });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [load, researchJobId]);

  const currentByCode = new Map<string, ProfileSection>();
  for (const section of data?.sections || []) {
    if (!currentByCode.has(section.section_code)) currentByCode.set(section.section_code, section);
  }

  const save = async (code: string, infoStatus: ProfileSection['info_status']) => {
    setSaving(true);
    try {
      await profileSections.write(entityType, entityId, {
        section_code: code,
        info_status: infoStatus,
        content_text: infoStatus === 'filled' ? draft : null,
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

  const startResearch = async () => {
    setResearching(true);
    setError(null);
    try {
      const job = await research.startSellerTarget(entityId);
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
      <div className="flex items-center gap-2 border border-gray-200 bg-white px-4 py-3 text-xs text-gray-400">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        加载匹配画像…
      </div>
    );
  }

  return (
    <div className="border border-gray-200 bg-white">
      <div className="flex items-center justify-between border-b border-gray-100 px-4 py-2">
        <h2 className="text-sm font-semibold text-gray-900">匹配画像</h2>
        <div className="flex items-center gap-3">
          {data && (
            <span className="text-xs text-gray-400">
              已填 {data.coverage.filled_sections.length}/{data.section_catalog.length}
              {data.coverage.missing_sections.length > 0 && ` 待补：${data.coverage.missing_sections.join('、')}`}
            </span>
          )}
          {entityType === 'seller_target' && (
            <button
              type="button"
              disabled={researching}
              onClick={() => void startResearch()}
              className="inline-flex items-center gap-1 border border-brand-200 px-2.5 py-1 text-xs text-brand-700 disabled:opacity-50"
            >
              {researching ? <Loader2 className="h-3 w-3 animate-spin" /> : <Search className="h-3 w-3" />}
              {researching ? '调研中' : '公开信息调研'}
            </button>
          )}
        </div>
      </div>
      {error && <p className="border-b border-red-100 bg-red-50 px-4 py-1.5 text-xs text-red-600">{error}</p>}
      <div className="divide-y divide-gray-100">
        {(data?.section_catalog || []).map((entry) => {
          const section = currentByCode.get(entry.code);
          const isEditing = editing === entry.code;
          return (
            <div key={entry.code} className="px-4 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-gray-700">{entry.label}</span>
                {!isEditing && (
                  <button
                    type="button"
                    onClick={() => {
                      setEditing(entry.code);
                      setDraft(section?.content_text || '');
                    }}
                    className="inline-flex items-center gap-1 text-xs text-brand-600 hover:underline"
                  >
                    <Pencil className="h-3 w-3" />
                    {section ? '编辑' : '填写'}
                  </button>
                )}
              </div>
              {isEditing ? (
                <div className="mt-1.5 space-y-1.5">
                  <textarea
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    rows={3}
                    className="w-full border border-gray-200 px-2 py-1.5 text-xs outline-none focus:border-brand-600"
                    placeholder="只写结构化字段装不下的定性判断，财务数字留在字段里"
                  />
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      disabled={saving || !draft.trim()}
                      onClick={() => void save(entry.code, 'filled')}
                      className="inline-flex items-center gap-1 bg-brand-600 px-2.5 py-1 text-xs text-white disabled:opacity-40"
                    >
                      <Check className="h-3 w-3" />
                      保存
                    </button>
                    <button
                      type="button"
                      disabled={saving}
                      onClick={() => void save(entry.code, 'not_found')}
                      className="border border-gray-200 px-2.5 py-1 text-xs text-gray-600 disabled:opacity-40"
                      title="明确记录为暂无信息，深评据此知道这是缺口而非不相关"
                    >
                      标为暂无信息
                    </button>
                    <button
                      type="button"
                      disabled={saving}
                      onClick={() => void save(entry.code, 'not_applicable')}
                      className="border border-gray-200 px-2.5 py-1 text-xs text-gray-600 disabled:opacity-40"
                    >
                      不适用
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditing(null)}
                      className="text-xs text-gray-400 hover:text-gray-600"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <p className={`mt-0.5 text-xs ${section ? 'text-gray-600' : 'text-gray-300'}`}>
                    {section
                      ? section.info_status === 'filled'
                        ? section.content_text
                        : `（${STATUS_LABELS[section.info_status]}）`
                      : '未填写'}
                  </p>
                  {section && (section.source_title || section.source_type) && (
                    <p className="mt-1 text-[11px] text-gray-400">
                      来源：{section.source_url ? (
                        <a href={section.source_url} target="_blank" rel="noreferrer" className="hover:text-brand-600 hover:underline">
                          {section.source_title || sourceTypeLabel(section.source_type)}
                        </a>
                      ) : section.source_title || sourceTypeLabel(section.source_type)}
                      {section.as_of_date && ` · 截至 ${section.as_of_date}`}
                      {section.confidence !== null && ` · 置信度 ${Math.round(section.confidence * 100)}%`}
                    </p>
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>
      {proposals.length > 0 && (
        <div className="border-t border-amber-100 bg-amber-50/50 px-4 py-3">
          <p className="text-xs font-medium text-amber-800">待确认调研建议（{proposals.length}）</p>
          <div className="mt-2 space-y-2">
            {proposals.map((proposal) => {
              // 调研查过但没有公开信息时提议 not_found —— 内容为空是正常的，
              // 它提议的是「确认这一栏是缺口」而不是一段描述。
              const proposed = proposal.proposal_kind !== 'profile_section'
                ? String(proposal.proposed_value_json.value || '')
                : proposal.proposed_value_json.info_status === 'not_found'
                  ? '公开渠道未找到相关信息，建议标记为暂无信息'
                  : String(proposal.proposed_value_json.content_text || '');
              const sources = Array.isArray(proposal.proposed_value_json.sources)
                ? (proposal.proposed_value_json.sources as string[])
                : [];
              return (
                <div key={proposal.id} className="border border-amber-100 bg-white px-3 py-2 text-xs">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-medium text-gray-700">
                        {proposal.section_label || fieldLabel('seller_target', proposal.field_path || '')}
                        <span className="ml-2 font-normal text-amber-700">{conflictLabel(proposal.conflict_kind)}</span>
                      </p>
                      <p className="mt-1 text-gray-600">{proposed}</p>
                      {(sources.length ? sources : proposal.source_url ? [proposal.source_url] : []).map((url) => (
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
                        disabled={reviewingProposalId === proposal.id}
                        onClick={() => void reviewProposal(proposal.id, 'accept')}
                        className="bg-brand-600 px-2 py-1 text-white disabled:opacity-50"
                      >确认</button>
                      <button
                        type="button"
                        disabled={reviewingProposalId === proposal.id}
                        onClick={() => void reviewProposal(proposal.id, 'reject')}
                        className="border border-gray-200 px-2 py-1 text-gray-500 disabled:opacity-50"
                      >忽略</button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
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

function conflictLabel(kind: ResearchProposal['conflict_kind']): string {
  return {
    consistent: '与现有信息一致',
    supplement: '补充信息',
    temporal_update: '新期间信息',
    same_period_conflict: '与当前信息冲突',
  }[kind];
}
