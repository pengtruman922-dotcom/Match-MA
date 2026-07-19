import { useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, ChevronDown, ChevronRight, ExternalLink, Loader2, Plus, RefreshCw } from 'lucide-react';
import type { CandidateView, Round } from './timeline';

const PREVIEW_COUNT = 5;

export default function RoundGroup({
  round,
  roundNumber,
  isLatest,
  onToggleSelect,
  onRetryDeepEval,
}: {
  round: Round;
  roundNumber: number;
  isLatest: boolean;
  onToggleSelect: (candidate: CandidateView) => void;
  onRetryDeepEval: () => void;
}) {
  const [expandedOld, setExpandedOld] = useState(false);
  const [showAll, setShowAll] = useState(false);

  if (!isLatest && !expandedOld) {
    return (
      <button
        type="button"
        onClick={() => setExpandedOld(true)}
        className="flex w-full items-center gap-2 border border-gray-200 bg-gray-50 px-4 py-2 text-left text-xs text-gray-500 hover:border-gray-300"
      >
        <ChevronRight className="h-3.5 w-3.5" />
        第{roundNumber}轮筛选 · {round.candidates.length} 个候选 · 已被新一轮取代，点击展开回看
      </button>
    );
  }

  const visible = showAll ? round.candidates : round.candidates.slice(0, PREVIEW_COUNT);

  return (
    <div className={`border ${isLatest ? 'border-gray-200 bg-white' : 'border-gray-200 bg-gray-50'}`}>
      <div className="flex items-center justify-between gap-2 border-b border-gray-100 px-4 py-2">
        <div className="flex items-center gap-2 text-xs text-gray-600">
          {!isLatest && (
            <button type="button" onClick={() => setExpandedOld(false)} className="text-gray-400 hover:text-gray-600">
              <ChevronDown className="h-3.5 w-3.5" />
            </button>
          )}
          <span className="font-medium text-gray-800">第{roundNumber}轮筛选 · {round.candidates.length} 个候选</span>
          {!isLatest && <span className="text-gray-400">（已被取代，仅供回看）</span>}
        </div>
        <DeepEvalBadge state={round.deepEval} onRetry={isLatest ? onRetryDeepEval : undefined} />
      </div>
      <div className="divide-y divide-gray-100">
        {visible.map((candidate, index) => (
          <CandidateRow
            key={candidate.pairKey}
            candidate={candidate}
            index={index + 1}
            interactive={isLatest}
            onToggleSelect={() => onToggleSelect(candidate)}
          />
        ))}
      </div>
      {round.candidates.length > PREVIEW_COUNT && (
        <button
          type="button"
          onClick={() => setShowAll((current) => !current)}
          className="w-full border-t border-gray-100 px-4 py-2 text-center text-xs text-brand-600 hover:bg-brand-50"
        >
          {showAll ? '收起' : `展开其余 ${round.candidates.length - PREVIEW_COUNT} 项`}
        </button>
      )}
    </div>
  );
}

function DeepEvalBadge({ state, onRetry }: { state: Round['deepEval']; onRetry?: () => void }) {
  if (state === 'running') {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-amber-600">
        <Loader2 className="h-3 w-3 animate-spin" />
        AI 深评中
      </span>
    );
  }
  if (state === 'done') {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-emerald-600">
        <CheckCircle2 className="h-3 w-3" />
        深评完成
      </span>
    );
  }
  if (state === 'failed') {
    return (
      <span className="inline-flex items-center gap-2 text-xs text-gray-500">
        深评未完成
        {onRetry && (
          <button type="button" onClick={onRetry} className="inline-flex items-center gap-1 text-brand-600 hover:underline">
            <RefreshCw className="h-3 w-3" />
            重新深评
          </button>
        )}
      </span>
    );
  }
  return null;
}

function CandidateRow({
  candidate,
  index,
  interactive,
  onToggleSelect,
}: {
  candidate: CandidateView;
  index: number;
  interactive: boolean;
  onToggleSelect: () => void;
}) {
  return (
    <div className={`px-4 py-3 ${candidate.selected ? 'bg-emerald-50/50' : ''}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="w-4 shrink-0 font-mono text-xs text-gray-400">{index}</span>
          <span className="truncate text-sm font-semibold text-gray-900">{candidate.name}</span>
          {candidate.detailPath && (
            <Link
              to={candidate.detailPath}
              target="_blank"
              className="inline-flex shrink-0 items-center gap-0.5 text-xs text-brand-600 hover:underline"
            >
              详情
              <ExternalLink className="h-3 w-3" />
            </Link>
          )}
        </div>
        <span className="flex shrink-0 items-center gap-1">
          {candidate.deepEvalGrade && (
            <span
              className={`border px-2 py-0.5 text-xs font-semibold ${
                candidate.deepEvalGrade === 'A'
                  ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                  : candidate.deepEvalGrade === 'B'
                    ? 'border-blue-200 bg-blue-50 text-blue-700'
                    : 'border-gray-200 bg-gray-50 text-gray-500'
              }`}
            >
              {candidate.deepEvalGrade} 档
            </span>
          )}
          <span className="border border-brand-200 bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">
            {candidate.strength}
          </span>
        </span>
      </div>
      <div className="ml-6 mt-1 space-y-0.5 text-xs text-gray-600">
        {candidate.deepEvalReason && <p className="font-medium text-gray-800">AI 评估: {candidate.deepEvalReason}</p>}
        {candidate.matchSummary && <p className="text-emerald-700">匹配: {candidate.matchSummary}</p>}
        {candidate.gapSummary && <p className="text-amber-700">缺口: {candidate.gapSummary}</p>}
        {candidate.deepEvalRisks && candidate.deepEvalRisks !== '暂无' && (
          <p className="text-amber-600">AI 风险: {candidate.deepEvalRisks}</p>
        )}
        {candidate.riskSummary && <p className="text-gray-400">风险: {candidate.riskSummary}</p>}
      </div>
      {interactive && (
        <div className="ml-6 mt-1.5">
          {candidate.selected ? (
            <span className="inline-flex items-center gap-2">
              <span className="inline-flex items-center gap-1 bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white">
                <CheckCircle2 className="h-3 w-3" />
                已加入推荐列表
              </span>
              <button type="button" onClick={onToggleSelect} className="text-xs text-gray-500 hover:text-red-600">
                取消
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={onToggleSelect}
              className="inline-flex items-center gap-1 border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-700 transition-colors hover:border-brand-500 hover:bg-brand-50 hover:text-brand-600"
            >
              <Plus className="h-3 w-3" />
              加入推荐列表
            </button>
          )}
        </div>
      )}
    </div>
  );
}
