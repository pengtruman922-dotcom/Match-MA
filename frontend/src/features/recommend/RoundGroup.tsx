import { useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, ChevronRight, ExternalLink, Loader2, Lock, Plus, RefreshCw, UserRound } from 'lucide-react';
import type { CandidateView, Round } from './timeline';
import { relationStatusLabel } from '../relations/relationLabels';

const PREVIEW_COUNT = 5;

export default function RoundGroup({
  round,
  roundNumber,
  isLatest,
  onToggleSelect,
  onStartProgress,
  onBlockedOperation,
  startingProgressKey,
  onRetryDeepEval,
  totalCandidateCount = round.candidates.length,
  emptyMessage = '当前筛选下没有可展示的候选',
  readOnly = false,
}: {
  round: Round;
  roundNumber: number;
  isLatest: boolean;
  onToggleSelect: (candidate: CandidateView) => void;
  onStartProgress: (candidate: CandidateView) => void;
  onBlockedOperation: (candidate: CandidateView) => void;
  startingProgressKey: string | null;
  onRetryDeepEval: () => void;
  totalCandidateCount?: number;
  emptyMessage?: string;
  /** Temporary-filter sessions have no real counterpart to associate. */
  readOnly?: boolean;
}) {
  const [expandedOld, setExpandedOld] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const countLabel = round.candidates.length === totalCandidateCount
    ? `${totalCandidateCount} 个候选`
    : `显示 ${round.candidates.length}/${totalCandidateCount} 个候选`;

  if (!isLatest && !expandedOld) {
    return (
      <button
        type="button"
        onClick={() => setExpandedOld(true)}
        className="flex w-full items-center gap-2 border border-gray-200 bg-gray-50 px-4 py-2 text-left text-xs text-gray-500 hover:border-gray-300"
      >
        <ChevronRight className="h-3.5 w-3.5" />
        第{roundNumber}轮筛选 · {countLabel} · 已被新一轮取代，点击展开回看
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
          <span className="font-medium text-gray-800">第{roundNumber}轮筛选 · {countLabel}</span>
          {!isLatest && <span className="text-gray-400">（已被取代，仅供回看）</span>}
        </div>
        <DeepEvalBadge state={round.deepEval} onRetry={isLatest ? onRetryDeepEval : undefined} />
      </div>
      <FunnelBar funnel={round.funnel} />
      <div className="divide-y divide-gray-100">
        {visible.map((candidate, index) => (
          <CandidateRow
            key={candidate.pairKey}
            candidate={candidate}
            index={index + 1}
            interactive={isLatest}
            onToggleSelect={() => onToggleSelect(candidate)}
            onStartProgress={() => onStartProgress(candidate)}
            onBlockedOperation={() => onBlockedOperation(candidate)}
            startingProgress={startingProgressKey === candidate.pairKey}
            readOnly={readOnly}
          />
        ))}
        {round.candidates.length === 0 && (
          <p className="px-4 py-8 text-center text-sm text-gray-500">{emptyMessage}</p>
        )}
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

/** 漏斗四数不是调试信息：eligible 远大于深评预算就是"该收紧条件了"的业务信号。 */
function FunnelBar({ funnel }: { funnel: Round['funnel'] }) {
  if (!funnel) return null;
  const overflow = funnel.eligible_count > funnel.deep_eval_count;
  return (
    <div
      className={`flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-1.5 text-xs ${
        overflow ? 'border-amber-100 bg-amber-50/60 text-amber-800' : 'border-gray-100 bg-gray-50/60 text-gray-500'
      }`}
    >
      <span>全库扫描 {funnel.scan_count}</span>
      <span className="text-gray-300">›</span>
      <span>符合基础条件 {funnel.eligible_count}</span>
      {funnel.conflict_count > 0 && <span className="text-gray-400">（{funnel.conflict_count} 个条件冲突已排除）</span>}
      <span className="text-gray-300">›</span>
      <span>AI 深评 {funnel.deep_eval_count}</span>
      {funnel.scenario_count ? <span className="text-indigo-600">{funnel.scenario_count} 个方案并行筛选</span> : null}
      {overflow && (
        <span className="inline-flex items-center gap-1 font-medium">
          <AlertTriangle className="h-3 w-3" />
          还有 {funnel.eligible_count - funnel.deep_eval_count} 个未做深评，建议补充结构化条件
        </span>
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
  onStartProgress,
  onBlockedOperation,
  startingProgress,
  readOnly,
}: {
  candidate: CandidateView;
  index: number;
  interactive: boolean;
  onToggleSelect: () => void;
  onStartProgress: () => void;
  onBlockedOperation: () => void;
  startingProgress: boolean;
  readOnly: boolean;
}) {
  const [showComparison, setShowComparison] = useState(false);
  const progressPath = candidate.detailPath ? `${candidate.detailPath}?tab=progress` : null;
  const matches = Array.isArray(candidate.evidence.matches) ? candidate.evidence.matches.map(String) : [];
  const gaps = Array.isArray(candidate.evidence.gaps) ? candidate.evidence.gaps.map(String) : [];
  return (
    <div
      data-candidate-key={candidate.pairKey}
      data-owner-state={candidate.ownedByCurrentUser ? 'mine' : candidate.ownerUserId ? 'other' : 'unassigned'}
      className={`px-4 py-3 ${candidate.selected ? 'bg-emerald-50/50' : ''}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="w-4 shrink-0 font-mono text-xs text-gray-400">{index}</span>
          <span className="truncate text-sm font-semibold text-gray-900">{candidate.name}</span>
          {candidate.relationStatus && (
            <span className="shrink-0 bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-700">
              已在推进 · {relationStatusLabel(candidate.relationStatus)}
            </span>
          )}
          {!candidate.relationStatus && candidate.hasOtherDeepProgress && (
            <span className="inline-flex shrink-0 items-center gap-0.5 bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">
              <Lock className="h-2.5 w-2.5" />
              {candidate.mode === 'buyer_to_target' ? '正与其他买家深入推进' : '正与其他标的深入推进'}
            </span>
          )}
          <OwnerBadge candidate={candidate} />
          {candidate.detailPath && candidate.operationAllowed && (
            <Link
              to={candidate.detailPath}
              target="_blank"
              data-action="detail"
              className="inline-flex shrink-0 items-center gap-0.5 text-xs text-brand-600 hover:underline"
            >
              详情
              <ExternalLink className="h-3 w-3" />
            </Link>
          )}
          {candidate.detailPath && !candidate.operationAllowed && (
            <button
              type="button"
              onClick={onBlockedOperation}
              data-action="detail"
              className="inline-flex shrink-0 items-center gap-0.5 text-xs text-brand-600 hover:underline"
            >
              详情
              <ExternalLink className="h-3 w-3" />
            </button>
          )}
        </div>
        <span className="flex shrink-0 items-center gap-1">
          {candidate.bestScenarioLabel && (
            <span className="border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">
              {candidate.bestScenarioLabel}
            </span>
          )}
          <span className="border border-brand-200 bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">
            {candidate.strength}
          </span>
        </span>
      </div>
      <div className="ml-6 mt-1 space-y-0.5 text-xs text-gray-600">
        <p className="text-gray-500">初筛情况：{matches.length} 项满足 · {candidate.missingDimensions.length} 项未知 · 0 项冲突</p>
        {candidate.deepEvalReason && <p className="font-medium text-gray-800">AI 评估: {candidate.deepEvalReason}</p>}
        {candidate.matchSummary && <p className="text-emerald-700">匹配: {candidate.matchSummary}</p>}
        {candidate.gapSummary && <p className="text-amber-700">缺口: {candidate.gapSummary}</p>}
        {candidate.deepEvalRisks && candidate.deepEvalRisks !== '暂无' && (
          <p className="text-amber-600">AI 风险: {candidate.deepEvalRisks}</p>
        )}
        {candidate.matchedScenarioLabels.filter((label) => label !== candidate.bestScenarioLabel).length > 0 && (
          <p className="text-indigo-600">
            同时满足: {candidate.matchedScenarioLabels.filter((label) => label !== candidate.bestScenarioLabel).join('、')}
          </p>
        )}
        {candidate.missingDimensions.length > 0 && (
          <p className="text-gray-500">待确认: {candidate.missingDimensions.join('、')}</p>
        )}
        {candidate.riskSummary && <p className="text-gray-400">风险: {candidate.riskSummary}</p>}
      </div>
      <div className="ml-6 mt-1.5">
        <button type="button" onClick={() => setShowComparison((value) => !value)} className="text-xs text-brand-600 hover:underline">
          {showComparison ? '收起对比' : '完整对比'}
        </button>
        {showComparison ? (
          <div className="mt-2 grid gap-3 border border-gray-100 bg-gray-50 p-3 text-xs md:grid-cols-3">
            <ComparisonList title="明确满足" tone="green" items={matches} empty="暂无明确满足项" />
            <ComparisonList title="软性不足/需核对" tone="amber" items={gaps} empty="暂无已知不足" />
            <ComparisonList title="标的信息未知" tone="gray" items={candidate.missingDimensions} empty="暂无未知项" />
          </div>
        ) : null}
      </div>
      {interactive && !readOnly && (
        <div className="ml-6 mt-1.5 flex flex-wrap items-center gap-2">
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
              onClick={candidate.operationAllowed ? onToggleSelect : onBlockedOperation}
              data-action="select"
              className="inline-flex items-center gap-1 border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-700 transition-colors hover:border-brand-500 hover:bg-brand-50 hover:text-brand-600"
            >
              <Plus className="h-3 w-3" />
              加入推荐列表
            </button>
          )}
          {candidate.relationStatus && progressPath && candidate.operationAllowed ? (
            <Link
              to={progressPath}
              target="_blank"
              data-action="view-progress"
              className="inline-flex items-center gap-1 border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100"
            >
              查看推进
              <ArrowRight className="h-3 w-3" />
            </Link>
          ) : candidate.relationStatus && progressPath ? (
            <button
              type="button"
              onClick={onBlockedOperation}
              data-action="view-progress"
              className="inline-flex items-center gap-1 border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100"
            >
              查看推进
              <ArrowRight className="h-3 w-3" />
            </button>
          ) : (
            <button
              type="button"
              onClick={candidate.operationAllowed ? onStartProgress : onBlockedOperation}
              data-action="start-progress"
              disabled={startingProgress}
              className="inline-flex items-center gap-1 border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-700 transition-colors hover:border-brand-500 hover:bg-brand-50 hover:text-brand-600 disabled:opacity-50"
            >
              {startingProgress ? <Loader2 className="h-3 w-3 animate-spin" /> : <ArrowRight className="h-3 w-3" />}
              开始推进
            </button>
          )}
        </div>
      )}
      {interactive && readOnly && (
        <p className="ml-6 mt-1.5 text-xs text-amber-700">临时筛选结果仅供查看；选择已有对象后可发起关联或推进。</p>
      )}
    </div>
  );
}

function OwnerBadge({ candidate }: { candidate: CandidateView }) {
  if (candidate.ownedByCurrentUser) {
    return (
      <span className="inline-flex shrink-0 items-center gap-0.5 bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-700">
        <UserRound className="h-2.5 w-2.5" />
        我负责
      </span>
    );
  }
  if (!candidate.ownerUserId) {
    return (
      <span className="inline-flex shrink-0 items-center gap-0.5 bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">
        <Lock className="h-2.5 w-2.5" />
        未指派
      </span>
    );
  }
  return (
    <span className="inline-flex shrink-0 items-center gap-0.5 bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">
      <Lock className="h-2.5 w-2.5" />
      {candidate.operationAllowed ? '负责人' : '其他用户负责'} · {candidate.ownerName || '未知用户'}
    </span>
  );
}

function ComparisonList({ title, tone, items, empty }: { title: string; tone: 'green' | 'amber' | 'gray'; items: string[]; empty: string }) {
  const color = tone === 'green' ? 'text-emerald-700' : tone === 'amber' ? 'text-amber-700' : 'text-gray-600';
  return <div><p className={`font-medium ${color}`}>{title}</p>{items.length ? <ul className="mt-1 space-y-1">{items.map((item, index) => <li key={`${item}-${index}`}>· {item}</li>)}</ul> : <p className="mt-1 text-gray-400">{empty}</p>}</div>;
}
