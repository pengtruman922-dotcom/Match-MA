import { useState } from 'react';
import { ExternalLink, Loader2 } from 'lucide-react';
import type { IndicatorRegistryResponse, ResearchProposal } from '../../types/api';
import { formatYuan } from '../../lib/format';
import { parseYuanInput } from './presentation';

const CONFLICT_LABELS: Record<string, string> = {
  consistent: '与当前值一致',
  supplement: '补充空字段',
  temporal_update: '更新到更晚的期间',
  same_period_conflict: '与现有信息冲突',
};

const SOURCE_LABELS: Record<string, string> = {
  material: '材料',
  web: '联网调研',
};

/**
 * 挂在对应字段旁边的一条待确认建议。
 *
 * 不做独立的「待办复核页」—— 标的侧的选择是把提案挂在字段旁边，因为顾问看的
 * 就是那张信息页，多开一个页面等于多一个没人去的地方。
 *
 * 真冲突时**两条来源并排展示**：归一节点故意没有裁决，让人看到双方证据再定。
 */
export default function PartyProposalCard({
  proposal,
  registry,
  busy,
  onReview,
}: {
  proposal: ResearchProposal;
  registry: IndicatorRegistryResponse | null;
  busy: boolean;
  onReview: (proposalId: string, decision: 'accept' | 'reject', reviewedValue?: unknown) => Promise<void>;
}) {
  const indicator = proposal.field_path
    ? registry?.indicators.find((item) => item.column === proposal.field_path)
    : undefined;
  const label = indicator?.label || proposal.field_path || '建议';
  const actionable = proposal.is_actionable !== false && !proposal.validation_error;
  const alternative = proposal.proposed_value_json.alternative as Record<string, unknown> | undefined;
  const crossSourceNote = proposal.proposed_value_json.cross_source_note as string | undefined;
  const sources = Array.isArray(proposal.proposed_value_json.sources)
    ? (proposal.proposed_value_json.sources as string[])
    : proposal.source_url
      ? [proposal.source_url]
      : [];
  const [modifying, setModifying] = useState(false);
  const [draft, setDraft] = useState('');
  const [draftError, setDraftError] = useState<string | null>(null);

  const beginModify = () => {
    const value = proposal.normalized_proposed_value ?? proposal.proposed_value_json.value;
    setDraft(formatFieldValue(value, indicator));
    setDraftError(null);
    setModifying(true);
  };

  const acceptModified = async () => {
    let reviewedValue: unknown = draft.trim();
    if (indicator?.kind === 'yuan') {
      const parsed = parseYuanInput(draft);
      if (parsed === null) {
        setDraftError('请输入有效金额，例如 32.6亿 或 3260万。');
        return;
      }
      reviewedValue = parsed;
    } else if (!draft.trim()) {
      setDraftError('修改后的内容不能为空。');
      return;
    }
    setDraftError(null);
    await onReview(proposal.id, 'accept', reviewedValue);
    setModifying(false);
  };

  return (
    <div className="mt-2 border-l-2 border-amber-300 bg-amber-50/60 px-3 py-2 text-xs">
      <p className="font-medium text-gray-700">
        {label}
        <span className="ml-2 font-normal text-amber-700">
          {CONFLICT_LABELS[proposal.conflict_kind] || proposal.conflict_kind}
        </span>
        <span className="ml-2 font-normal text-gray-400">
          来源：{SOURCE_LABELS[proposal.source_type || ''] || proposal.source_type || '未注明'}
        </span>
      </p>

      <div className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-1 text-gray-700">
        <span className="text-gray-400">当前</span>
        <span className="break-words">{formatFieldValue(proposal.current_value_json.value, indicator) || '空'}</span>
        <span className="text-amber-700">建议</span>
        <span className="break-words font-medium text-amber-800">
          {formatFieldValue(proposal.normalized_proposed_value ?? proposal.proposed_value_json.value, indicator)}
        </span>
      </div>

      {/* 财务数字必须带时间一起显示：没有时间的财务数字是不可用的。 */}
      {proposal.period_label || proposal.as_of_date ? (
        <p className="mt-1 text-[11px] text-gray-400">时间：{proposal.period_label || proposal.as_of_date}</p>
      ) : null}

      {alternative ? (
        <div className="mt-2 border border-amber-200 bg-white/70 px-2 py-1.5">
          <p className="text-[11px] text-gray-500">
            另一条来源（{SOURCE_LABELS[String(alternative.source_type || '')] || '未注明'}）：
            <span className="ml-1 font-medium text-gray-800">
              {formatFieldValue(alternative.value, indicator)}
            </span>
          </p>
          {alternative.source_excerpt ? (
            <p className="mt-1 text-[11px] leading-5 text-gray-500">「{String(alternative.source_excerpt)}」</p>
          ) : null}
        </div>
      ) : null}

      {crossSourceNote ? <p className="mt-1 text-[11px] text-gray-500">{crossSourceNote}</p> : null}
      {proposal.source_excerpt ? (
        <p className="mt-1 text-[11px] leading-5 text-gray-500">「{proposal.source_excerpt}」</p>
      ) : null}
      {!actionable ? (
        <p className="mt-1 text-red-600">原建议值无法直接写入：{proposal.validation_error || '请修改后再采纳'}</p>
      ) : null}
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

      {modifying ? (
        <div className="mt-2 space-y-1.5">
          <input className="input" value={draft} onChange={(event) => setDraft(event.target.value)} autoFocus />
          {draftError ? <p className="text-red-600">{draftError}</p> : null}
          <div className="flex justify-end gap-1.5">
            <button
              type="button"
              disabled={busy}
              onClick={() => void acceptModified()}
              className="bg-brand-600 px-2 py-1 text-white disabled:opacity-50"
            >
              保存并采纳
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setModifying(false)}
              className="border border-gray-200 px-2 py-1 text-gray-600"
            >
              取消
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-2 flex flex-wrap justify-end gap-1.5">
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-400" /> : null}
          {actionable ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void onReview(proposal.id, 'accept')}
              className="bg-brand-600 px-2 py-1 text-white disabled:opacity-50"
            >
              采纳
            </button>
          ) : null}
          <button
            type="button"
            disabled={busy}
            onClick={beginModify}
            className="border border-gray-300 px-2 py-1 text-gray-700 disabled:opacity-50"
          >
            修改并采纳
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void onReview(proposal.id, 'reject')}
            className="border border-gray-300 px-2 py-1 text-gray-700 disabled:opacity-50"
          >
            忽略
          </button>
        </div>
      )}
    </div>
  );
}

function formatFieldValue(
  value: unknown,
  indicator: IndicatorRegistryResponse['indicators'][number] | undefined,
): string {
  if (value === null || value === undefined || value === '') return '';
  if (Array.isArray(value)) return value.map((item) => String(item)).join('、');
  if (indicator?.enum_options?.length) {
    const option = indicator.enum_options.find((item) => item.value === String(value));
    if (option) return option.label;
  }
  if (indicator?.kind === 'yuan') {
    // 建议值可能仍是 { value, unit } 的原始形状（归一由写入端做）。
    if (typeof value === 'object') {
      const record = value as Record<string, unknown>;
      return `${record.value ?? ''}${record.unit ?? ''}`;
    }
    return formatYuan(value as string | number);
  }
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function sourceDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}
