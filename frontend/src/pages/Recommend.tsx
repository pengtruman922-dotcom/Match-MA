import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ArrowRightLeft, Loader2, Send, Sparkles } from 'lucide-react';
import { buyerIntents, recommendations, sellerTargets } from '../lib/api';
import type { BuyerIntent, RecommendationSelectedItem, SellerTarget } from '../types/api';
import ConditionChips, { intentConditionChips, targetConditionChips } from '../features/recommend/ConditionChips';
import ObjectSelect, { type ObjectOption } from '../features/recommend/ObjectSelect';
import RoundGroup from '../features/recommend/RoundGroup';
import ReportModal from '../features/recommend/ReportModal';
import SelectedDrawer from '../features/recommend/SelectedDrawer';
import SessionPicker from '../features/recommend/SessionPicker';
import TinyMarkdown from '../features/recommend/TinyMarkdown';
import {
  buildTimeline,
  latestRoundEntry,
  levelToApi,
  type CandidateView,
  type TimelineEntry,
} from '../features/recommend/timeline';

type Mode = 'buyer_to_target' | 'target_to_buyer';

const DEEP_EVAL_POLL_INTERVAL_MS = 5000;
const DEEP_EVAL_POLL_MAX_ATTEMPTS = 36;

export default function Recommend() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [mode, setMode] = useState<Mode>(searchParams.get('mode') === 'target-to-buyer' ? 'target_to_buyer' : 'buyer_to_target');
  const [intent, setIntent] = useState<BuyerIntent | null>(null);
  const [target, setTarget] = useState<SellerTarget | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [selectedItems, setSelectedItems] = useState<RecommendationSelectedItem[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reportOpen, setReportOpen] = useState(false);

  const pollRef = useRef<number | null>(null);
  const bootstrappedRef = useRef(false);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const anchorReady = mode === 'buyer_to_target' ? Boolean(intent) : Boolean(target);
  const anchorLabel = mode === 'buyer_to_target'
    ? intent ? `${intent.buyer_name ? `${intent.buyer_name} / ` : ''}${intent.intent_name}` : ''
    : target ? target.target_name : '';
  const chips = mode === 'buyer_to_target'
    ? intent ? intentConditionChips(intent) : []
    : target ? targetConditionChips(target) : [];

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [timeline.length, generating]);

  const markLatestRound = useCallback((deepEval: 'running' | 'failed') => {
    setTimeline((prev) => {
      const next = [...prev];
      for (let index = next.length - 1; index >= 0; index -= 1) {
        const entry = next[index];
        if (entry.kind === 'round') {
          if (entry.round.deepEval !== 'done') {
            next[index] = { ...entry, round: { ...entry.round, deepEval } };
          }
          break;
        }
      }
      return next;
    });
  }, []);

  const refreshFromServer = useCallback(async (activeSessionId: string): Promise<'done' | 'pending' | 'failed'> => {
    const bundle = await recommendations.bundle(activeSessionId);
    setTimeline(buildTimeline(bundle));
    setSelectedItems((bundle.selected_items || []).filter((item) => !item.canceled_at));
    const status = String(bundle.rerank_status?.status || '');
    if ((bundle.reranked_candidates || []).length > 0 && !['queued', 'running', 'retry_waiting'].includes(status)) return 'done';
    if (status === 'failed') return 'failed';
    if (['queued', 'running', 'retry_waiting'].includes(status)) return 'pending';
    return 'done';
  }, []);

  const startDeepEvalPolling = useCallback((activeSessionId: string) => {
    stopPolling();
    let attempts = 0;
    pollRef.current = window.setInterval(async () => {
      attempts += 1;
      if (attempts > DEEP_EVAL_POLL_MAX_ATTEMPTS) {
        stopPolling();
        markLatestRound('failed');
        return;
      }
      try {
        const state = await refreshFromServer(activeSessionId);
        if (state === 'done' || state === 'failed') stopPolling();
      } catch {
        // 网络抖动继续轮询，由 attempts 上限兜底
      }
    }, DEEP_EVAL_POLL_INTERVAL_MS);
  }, [markLatestRound, refreshFromServer, stopPolling]);

  const loadIntentAnchor = useCallback(async (intentId: string): Promise<BuyerIntent | null> => {
    try {
      const loaded = await buyerIntents.get(intentId);
      setIntent(loaded);
      return loaded;
    } catch {
      setError('加载买家意向失败');
      return null;
    }
  }, []);

  const loadTargetAnchor = useCallback(async (targetId: string): Promise<SellerTarget | null> => {
    try {
      const loaded = await sellerTargets.get(targetId);
      setTarget(loaded);
      return loaded;
    } catch {
      setError('加载标的失败');
      return null;
    }
  }, []);

  const restoreSession = useCallback(async (restoreId: string) => {
    try {
      const bundle = await recommendations.bundle(restoreId);
      const session = bundle.session;
      const sessionMode = session.mode as Mode;
      setMode(sessionMode);
      setSessionId(restoreId);
      if (sessionMode === 'buyer_to_target' && session.buyer_intent_id) {
        await loadIntentAnchor(session.buyer_intent_id);
      } else if (sessionMode === 'target_to_buyer' && session.seller_target_id) {
        await loadTargetAnchor(session.seller_target_id);
      }
      setTimeline(buildTimeline(bundle));
      setSelectedItems((bundle.selected_items || []).filter((item) => !item.canceled_at));
      const status = String(bundle.rerank_status?.status || '');
      if (['queued', 'running', 'retry_waiting'].includes(status)) {
        startDeepEvalPolling(restoreId);
      }
    } catch {
      setError('恢复推荐会话失败，可能已被删除');
    }
  }, [loadIntentAnchor, loadTargetAnchor, startDeepEvalPolling]);

  useEffect(() => {
    if (bootstrappedRef.current) return;
    bootstrappedRef.current = true;
    const sessionParam = searchParams.get('session');
    const intentParam = searchParams.get('intentId');
    const targetParam = searchParams.get('targetId');
    if (sessionParam) {
      void restoreSession(sessionParam);
    } else if (intentParam) {
      void loadIntentAnchor(intentParam).then((loaded) => {
        if (loaded) setTimeline([welcomeEntry(buildIntentGuidance(loaded))]);
      });
    } else if (targetParam) {
      void loadTargetAnchor(targetParam).then((loaded) => {
        if (loaded) setTimeline([welcomeEntry(buildTargetGuidance(loaded))]);
      });
    }
  }, [searchParams, restoreSession, loadIntentAnchor, loadTargetAnchor]);

  const resetConversation = useCallback(() => {
    stopPolling();
    setSessionId(null);
    setTimeline([]);
    setSelectedItems([]);
    setError(null);
    const next = new URLSearchParams(searchParams);
    next.delete('session');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams, stopPolling]);

  const switchMode = (nextMode: Mode) => {
    if (nextMode === mode) return;
    setMode(nextMode);
    setIntent(null);
    setTarget(null);
    resetConversation();
  };

  const handlePickAnchor = async (option: ObjectOption) => {
    resetConversation();
    if (mode === 'buyer_to_target') {
      setTarget(null);
      const loaded = await loadIntentAnchor(option.id);
      if (loaded) setTimeline([welcomeEntry(buildIntentGuidance(loaded))]);
    } else {
      setIntent(null);
      const loaded = await loadTargetAnchor(option.id);
      if (loaded) setTimeline([welcomeEntry(buildTargetGuidance(loaded))]);
    }
  };

  const runRound = async (userMessage?: string) => {
    if (!anchorReady) {
      setError(mode === 'buyer_to_target' ? '请先选择买家意向' : '请先选择标的');
      return;
    }
    setGenerating(true);
    setError(null);
    stopPolling();
    if (userMessage) {
      setTimeline((prev) => [...prev, { kind: 'user', id: `local-${Date.now()}`, text: userMessage }]);
    }
    try {
      const response = await recommendations.candidates({
        mode,
        buyer_intent_id: mode === 'buyer_to_target' ? intent!.id : undefined,
        seller_target_id: mode === 'target_to_buyer' ? target!.id : undefined,
        limit: 20,
        create_session: true,
        session_id: sessionId || undefined,
        user_message: userMessage,
      });
      const activeSessionId = response.session_id;
      if (!activeSessionId) {
        setError('创建推荐会话失败');
        return;
      }
      if (!sessionId) {
        setSessionId(activeSessionId);
        const next = new URLSearchParams(searchParams);
        next.set('session', activeSessionId);
        setSearchParams(next, { replace: true });
      }
      const state = await refreshFromServer(activeSessionId);
      const deepEvalRequested = Boolean((response.debug as Record<string, unknown>)?.rerank);
      if (deepEvalRequested && state === 'pending') {
        startDeepEvalPolling(activeSessionId);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : '生成推荐失败';
      setError(message);
      setTimeline((prev) => [...prev, { kind: 'system', id: `local-err-${Date.now()}`, text: `生成推荐失败：${message}` }]);
    } finally {
      setGenerating(false);
    }
  };

  const handleSend = () => {
    const message = inputValue.trim();
    if (!message || generating) return;
    setInputValue('');
    void runRound(message);
  };

  const updateCandidateSelection = (pairKey: string, selected: boolean, selectedItemId: string | null) => {
    setTimeline((prev) =>
      prev.map((entry) => {
        if (entry.kind !== 'round') return entry;
        return {
          ...entry,
          round: {
            ...entry.round,
            candidates: entry.round.candidates.map((candidate) =>
              candidate.pairKey === pairKey ? { ...candidate, selected, selectedItemId } : candidate
            ),
          },
        };
      })
    );
  };

  const toggleSelect = async (candidate: CandidateView) => {
    if (!sessionId) return;
    if (candidate.selected && candidate.selectedItemId) {
      try {
        await recommendations.cancelSelectedItem(candidate.selectedItemId);
        updateCandidateSelection(candidate.pairKey, false, null);
        setSelectedItems((prev) => prev.filter((item) => item.id !== candidate.selectedItemId));
      } catch (err) {
        setError(err instanceof Error ? err.message : '取消推荐项失败');
      }
      return;
    }
    const latest = latestRoundEntry(timeline);
    const rank = latest ? latest.round.candidates.findIndex((item) => item.pairKey === candidate.pairKey) + 1 : 1;
    try {
      const selectedItem = await recommendations.selectItem(sessionId, {
        mode: candidate.mode,
        seller_target_id: candidate.sellerTargetId,
        buyer_intent_id: candidate.buyerIntentId,
        buyer_party_id: candidate.buyerPartyId,
        rank_at_selection: Math.max(rank, 1),
        recommendation_level: levelToApi(candidate.strength),
        match_summary: candidate.matchSummary,
        risk_summary: candidate.riskSummary,
        gap_summary: candidate.gapSummary,
        reason_snapshot: candidate.deepEvalReason || candidate.matchSummary,
        evidence_snapshot_json: candidate.evidence,
      });
      updateCandidateSelection(candidate.pairKey, true, selectedItem.id);
      setSelectedItems((prev) => [...prev, selectedItem]);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加入推荐列表失败');
    }
  };

  const removeSelected = async (item: RecommendationSelectedItem) => {
    try {
      await recommendations.cancelSelectedItem(item.id);
      setSelectedItems((prev) => prev.filter((existing) => existing.id !== item.id));
      updateCandidateSelection(`${item.seller_target_id || ''}:${item.buyer_intent_id || ''}`, false, null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '取消推荐项失败');
    }
  };

  const retryDeepEval = async () => {
    if (!sessionId) return;
    try {
      await recommendations.createRerankJob(sessionId);
      markLatestRound('running');
      startDeepEvalPolling(sessionId);
    } catch (err) {
      setError(err instanceof Error ? err.message : '重新深评失败');
    }
  };

  const openSession = (pickId: string) => {
    stopPolling();
    setIntent(null);
    setTarget(null);
    setSessionId(null);
    setTimeline([]);
    setSelectedItems([]);
    const next = new URLSearchParams();
    next.set('session', pickId);
    setSearchParams(next);
    void restoreSession(pickId);
  };

  let roundCounter = 0;
  const latest = latestRoundEntry(timeline);

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-gray-900">智能推荐</h1>
          <div className="flex items-center border border-gray-200 bg-white p-0.5">
            <ModeButton active={mode === 'buyer_to_target'} onClick={() => switchMode('buyer_to_target')} label="为买家找标的" />
            <ModeButton active={mode === 'target_to_buyer'} onClick={() => switchMode('target_to_buyer')} label="为标的找买家" />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <SessionPicker onPick={openSession} />
          <SelectedDrawer items={selectedItems} onRemove={(item) => void removeSelected(item)} onOpenReport={() => setReportOpen(true)} />
        </div>
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-2 border border-gray-200 bg-white px-3 py-2">
        <span className="text-xs text-gray-500">对象:</span>
        <ObjectSelect
          placeholder={mode === 'buyer_to_target' ? '搜索选择买家意向...' : '搜索选择标的...'}
          displayLabel={anchorLabel}
          onSelect={(option) => void handlePickAnchor(option)}
          fetchOptions={async (q) => {
            if (mode === 'buyer_to_target') {
              const response = await buyerIntents.list({ q: q || undefined, status: 'active', limit: 20 });
              return response.items.map((item) => ({ id: item.id, label: item.intent_name, subtitle: item.buyer_name || undefined }));
            }
            const response = await sellerTargets.list({ q: q || undefined, limit: 20 });
            return response.items.map((item) => ({ id: item.id, label: item.target_name, subtitle: item.business_summary || undefined }));
          }}
        />
        <button
          onClick={() => void runRound()}
          disabled={generating || !anchorReady}
          className="ml-auto inline-flex items-center gap-1.5 bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-40"
        >
          {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          开始推荐
        </button>
      </div>

      {chips.length > 0 && <div className="mb-2"><ConditionChips chips={chips} /></div>}
      {error && <div className="mb-2 border border-red-200 bg-red-50 px-4 py-2 text-xs text-red-700">{error}</div>}

      <div className="flex min-h-0 flex-1 flex-col border border-gray-200 bg-gray-50/60">
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {timeline.length === 0 && (
            <div className="border border-gray-200 bg-white px-4 py-3 text-sm text-gray-600">
              <p className="mb-1 font-medium text-gray-800">
                {anchorReady ? '已加载对象条件。' : mode === 'buyer_to_target' ? '请先选择买家意向。' : '请先选择标的。'}
              </p>
              <p className="text-xs text-gray-500">选择对象后点击「开始推荐」，或在下方输入补充条件。</p>
            </div>
          )}
          {timeline.map((entry) => {
            if (entry.kind === 'user') {
              return (
                <div key={entry.id} className="flex justify-end">
                  <div className="max-w-[70%] border-l-2 border-l-brand-600 bg-brand-50 px-4 py-2.5">
                    <p className="whitespace-pre-line text-sm text-gray-800">{entry.text}</p>
                  </div>
                </div>
              );
            }
            if (entry.kind === 'system') {
              return (
                <div key={entry.id} className="max-w-[85%] border border-gray-200 bg-white px-4 py-2.5">
                  <p className="whitespace-pre-line text-sm text-gray-700">{entry.text}</p>
                </div>
              );
            }
            if (entry.kind === 'report') {
              return (
                <div key={entry.id} className="border border-violet-200 bg-violet-50/50">
                  <p className="border-b border-violet-100 px-4 py-2 text-xs font-medium text-violet-700">推荐报告已生成</p>
                  <div className="max-h-64 overflow-y-auto px-4 py-3">
                    <TinyMarkdown text={entry.markdown} />
                  </div>
                </div>
              );
            }
            roundCounter += 1;
            return (
              <RoundGroup
                key={entry.id}
                round={entry.round}
                roundNumber={roundCounter}
                isLatest={latest?.id === entry.id}
                onToggleSelect={(candidate) => void toggleSelect(candidate)}
                onRetryDeepEval={() => void retryDeepEval()}
              />
            );
          })}
          {generating && (
            <div className="flex items-center gap-2 px-1 text-xs text-gray-400">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              正在生成推荐...
            </div>
          )}
          <div ref={chatEndRef} />
        </div>
        <div className="border-t border-gray-200 bg-white p-3">
          <div className="flex items-center gap-2 border border-gray-200 transition-all focus-within:border-brand-600">
            <input
              type="text"
              value={inputValue}
              onChange={(event) => setInputValue(event.target.value)}
              onKeyDown={(event) => event.key === 'Enter' && handleSend()}
              placeholder={anchorReady ? '输入补充条件（如：只看浙江、利润1500万以上），回车发送...' : '请先在上方选择对象...'}
              disabled={!anchorReady}
              className="flex-1 px-4 py-2.5 text-sm outline-none placeholder:text-gray-400 disabled:bg-gray-50"
            />
            <button
              onClick={handleSend}
              className="mr-2 bg-brand-600 p-2 text-white transition-colors hover:bg-brand-700 disabled:opacity-40"
              disabled={!inputValue.trim() || generating || !anchorReady}
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {reportOpen && sessionId && (
        <ReportModal
          sessionId={sessionId}
          selectedItems={selectedItems}
          defaultTitle={`${anchorLabel || '推荐'}-推荐报告-${new Date().toISOString().slice(5, 10).replace('-', '')}`}
          onClose={() => setReportOpen(false)}
          onGenerated={() => {
            if (sessionId) void refreshFromServer(sessionId);
          }}
        />
      )}
    </div>
  );
}

function ModeButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium transition-all ${
        active ? 'bg-brand-600 text-white' : 'text-gray-600 hover:text-brand-600'
      }`}
    >
      <ArrowRightLeft className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}

function welcomeEntry(text: string): TimelineEntry {
  return { kind: 'system', id: `welcome-${Date.now()}`, text };
}

function buildIntentGuidance(intent: BuyerIntent): string {
  const parts: string[] = [`已加载买家意向：${intent.intent_name}`];
  if (intent.industry_primary) parts.push(`行业：${intent.industry_primary}`);
  if (intent.region_scope_summary) parts.push(`地区：${intent.region_scope_summary}`);
  if (intent.min_net_profit_yuan) parts.push(`最低利润：${(Number(intent.min_net_profit_yuan) / 10000).toFixed(0)}万`);
  if (intent.max_pe) parts.push(`PE上限：${Number(intent.max_pe).toFixed(0)}`);
  if (intent.requires_consolidation && intent.requires_consolidation !== 'unknown') {
    parts.push(`并表要求：${intent.requires_consolidation === 'yes' ? '是' : '否'}`);
  }
  return [parts.join('\n'), '', '可以直接点击「开始推荐」，也可以输入补充条件。'].join('\n');
}

function buildTargetGuidance(target: SellerTarget): string {
  const parts: string[] = [`已加载标的：${target.target_name}`];
  if (target.industry_primary) parts.push(`行业：${target.industry_primary}`);
  if (target.headquarter_province) parts.push(`地区：${target.headquarter_province}${target.headquarter_city || ''}`);
  if (target.current_net_profit_yuan) parts.push(`利润：${(Number(target.current_net_profit_yuan) / 10000).toFixed(0)}万`);
  return [parts.join('\n'), '', '可以直接点击「开始推荐」为该标的匹配买家，也可以输入补充条件。'].join('\n');
}
