import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  ArrowRightLeft,
  Ban,
  Building2,
  CheckCircle2,
  Eye,
  FileText,
  Info,
  Loader2,
  MapPin,
  Plus,
  Send,
  Sparkles,
  Star,
  TrendingUp,
  X,
} from 'lucide-react';
import { buyerIntents, buyerParties, recommendations, sellerTargets } from '../lib/api';
import type { BuyerIntent, BuyerParty, RecommendationCandidate, SellerTarget } from '../types/api';

type Mode = 'buyer-to-target' | 'target-to-buyer';

interface RecommendationItem {
  id: string;
  sessionId: string | null;
  mode: 'buyer_to_target' | 'target_to_buyer';
  sellerTargetId: string | null;
  buyerIntentId: string | null;
  buyerPartyId: string | null;
  name: string;
  strength: string;
  matchSummary: string;
  gapSummary: string;
  riskSummary: string | null;
  evidence: Record<string, unknown>;
  deepEvalGrade: string | null;
  deepEvalReason: string | null;
  deepEvalRisks: string | null;
  inShortlist: boolean;
  persisted: boolean;
  selectedItemId: string | null;
}

type DeepEvalStatus = 'idle' | 'running' | 'done' | 'failed';

interface ChatMessage {
  role: 'user' | 'system';
  content: string;
}

export default function Recommend() {
  const [searchParams] = useSearchParams();
  const urlMode = searchParams.get('mode') as Mode | null;
  const urlIntentId = searchParams.get('intentId') || '';
  const urlTargetId = searchParams.get('targetId') || '';

  const [mode, setMode] = useState<Mode>(urlMode === 'target-to-buyer' ? 'target-to-buyer' : 'buyer-to-target');
  const [items, setItems] = useState<RecommendationItem[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [conditionsOpen, setConditionsOpen] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [deepEvalStatus, setDeepEvalStatus] = useState<DeepEvalStatus>('idle');
  const pollTimerRef = useRef<number | null>(null);

  const [targetsList, setTargetsList] = useState<SellerTarget[]>([]);
  const [intentsList, setIntentsList] = useState<BuyerIntent[]>([]);
  const [partiesList, setPartiesList] = useState<BuyerParty[]>([]);
  const [selectedIntentId, setSelectedIntentId] = useState(urlIntentId);
  const [selectedTargetId, setSelectedTargetId] = useState(urlTargetId);

  const initializedRef = useRef(false);

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) window.clearInterval(pollTimerRef.current);
    };
  }, []);

  useEffect(() => {
    sellerTargets.list({ limit: 50 }).then((response) => setTargetsList(response.items)).catch(() => {});
    buyerIntents.list({ status: 'active', limit: 50 }).then((response) => setIntentsList(response.items)).catch(() => {});
    buyerParties.list({ limit: 50 }).then((response) => setPartiesList(response.items)).catch(() => {});
  }, []);

  useEffect(() => {
    if (initializedRef.current) return;
    if (mode === 'buyer-to-target' && selectedIntentId && intentsList.length > 0) {
      const intent = intentsList.find((item) => item.id === selectedIntentId);
      if (intent) {
        initializedRef.current = true;
        setChatMessages([{ role: 'system', content: buildIntentGuidance(intent) }]);
      }
    } else if (mode === 'target-to-buyer' && selectedTargetId && targetsList.length > 0) {
      const target = targetsList.find((item) => item.id === selectedTargetId);
      if (target) {
        initializedRef.current = true;
        setChatMessages([{ role: 'system', content: buildTargetGuidance(target) }]);
      }
    }
  }, [mode, selectedIntentId, selectedTargetId, intentsList, targetsList]);

  const shortlistCount = items.filter((item) => item.inShortlist).length;
  const selectedIntent = intentsList.find((item) => item.id === selectedIntentId);
  const selectedTarget = targetsList.find((item) => item.id === selectedTargetId);
  const intentParty = selectedIntent?.buyer_party_id
    ? partiesList.find((party) => party.id === selectedIntent.buyer_party_id) ?? null
    : null;

  async function toggleShortlist(id: string) {
    const item = items.find((candidate) => candidate.id === id);
    if (!item) return;

    if (!item.inShortlist && item.sessionId && !item.persisted) {
      try {
        const selectedItem = await recommendations.selectItem(item.sessionId, {
          mode: item.mode,
          seller_target_id: item.sellerTargetId,
          buyer_intent_id: item.buyerIntentId,
          buyer_party_id: item.buyerPartyId,
          rank_at_selection: items.findIndex((candidate) => candidate.id === id) + 1,
          recommendation_level: levelToApi(item.strength),
          match_summary: item.matchSummary,
          risk_summary: item.riskSummary,
          gap_summary: item.gapSummary,
          reason_snapshot: item.matchSummary,
          evidence_snapshot_json: item.evidence,
        });
        setItems((prev) =>
          prev.map((candidate) =>
            candidate.id === id
              ? { ...candidate, inShortlist: true, persisted: true, selectedItemId: selectedItem.id }
              : candidate
          )
        );
        return;
      } catch (err) {
        setGenerationError(err instanceof Error ? err.message : '加入推荐列表失败');
      }
    }

    if (item.inShortlist && item.persisted && item.selectedItemId) {
      try {
        await recommendations.cancelSelectedItem(item.selectedItemId);
      } catch (err) {
        setGenerationError(err instanceof Error ? err.message : '取消推荐项失败');
        return;
      }
    }

    setItems((prev) =>
      prev.map((candidate) => {
        if (candidate.id !== id) return candidate;
        if (item.inShortlist && item.persisted) {
          return { ...candidate, inShortlist: false, persisted: false, selectedItemId: null };
        }
        return { ...candidate, inShortlist: !candidate.inShortlist };
      })
    );
  }

  function stopDeepEvalPolling() {
    if (pollTimerRef.current) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }

  function startDeepEvalPolling(sessionId: string) {
    stopDeepEvalPolling();
    setDeepEvalStatus('running');
    let attempts = 0;
    pollTimerRef.current = window.setInterval(async () => {
      attempts += 1;
      if (attempts > 36) {
        stopDeepEvalPolling();
        setDeepEvalStatus('failed');
        return;
      }
      try {
        const bundle = await recommendations.bundle(sessionId);
        const reranked = bundle.reranked_candidates || [];
        if (reranked.length > 0) {
          setItems((prev) => {
            const stateById = new Map(prev.map((item) => [item.id, item]));
            return reranked.map((candidate) => {
              const mapped = mapCandidate(candidate, sessionId);
              const previous = stateById.get(mapped.id);
              return previous
                ? { ...mapped, inShortlist: previous.inShortlist, persisted: previous.persisted, selectedItemId: previous.selectedItemId }
                : mapped;
            });
          });
          stopDeepEvalPolling();
          setDeepEvalStatus('done');
          return;
        }
        if (bundle.rerank_status?.status === 'failed') {
          stopDeepEvalPolling();
          setDeepEvalStatus('failed');
        }
      } catch {
        // 网络抖动继续轮询，由 attempts 上限兜底
      }
    }, 5000);
  }

  function switchMode(newMode: Mode) {
    setMode(newMode);
    setItems([]);
    setChatMessages([]);
    setSelectedIntentId('');
    setSelectedTargetId('');
    setGenerationError(null);
    stopDeepEvalPolling();
    setDeepEvalStatus('idle');
    initializedRef.current = false;
  }

  function handleSelectIntent(id: string) {
    setSelectedIntentId(id);
    setItems([]);
    if (id !== selectedIntentId) {
      initializedRef.current = false;
      setChatMessages([]);
    }
  }

  function handleSelectTarget(id: string) {
    setSelectedTargetId(id);
    setItems([]);
    if (id !== selectedTargetId) {
      initializedRef.current = false;
      setChatMessages([]);
    }
  }

  async function handleSend() {
    const message = inputValue.trim();
    if (!message) return;
    setChatMessages((prev) => [...prev, { role: 'user', content: message }]);
    setInputValue('');
    await generateCandidates(message);
  }

  async function generateCandidates(userMessage?: string) {
    if (mode === 'buyer-to-target' && !selectedIntentId) {
      setGenerationError('请先选择买家意向');
      return;
    }
    if (mode === 'target-to-buyer' && !selectedTargetId) {
      setGenerationError('请先选择标的');
      return;
    }

    setGenerating(true);
    setGenerationError(null);
    try {
      const response = await recommendations.candidates({
        mode: mode === 'buyer-to-target' ? 'buyer_to_target' : 'target_to_buyer',
        buyer_intent_id: mode === 'buyer-to-target' ? selectedIntentId : undefined,
        seller_target_id: mode === 'target-to-buyer' ? selectedTargetId : undefined,
        limit: 20,
        create_session: true,
        user_message: userMessage,
      });
      stopDeepEvalPolling();
      setDeepEvalStatus('idle');
      setItems(response.candidates.map((candidate) => mapCandidate(candidate, response.session_id)));
      const deepEvalRequested = Boolean((response.debug as Record<string, unknown>)?.rerank);
      if (response.session_id && deepEvalRequested) {
        startDeepEvalPolling(response.session_id);
      }
      setChatMessages((prev) => [
        ...prev,
        {
          role: 'system',
          content: deepEvalRequested
            ? `已生成 ${response.candidates.length} 个候选（规则初排）。AI 深度评估进行中，完成后将自动按评级重排并附推荐理由。`
            : `已生成 ${response.candidates.length} 个候选（规则排序）。`,
        },
      ]);
    } catch (err) {
      const message = err instanceof Error ? err.message : '生成推荐失败';
      setGenerationError(message);
      setChatMessages((prev) => [...prev, { role: 'system', content: `生成推荐失败：${message}` }]);
    } finally {
      setGenerating(false);
    }
  }

  const objectLabel = mode === 'buyer-to-target'
    ? (selectedIntent ? `${intentParty?.buyer_name || ''} / ${selectedIntent.intent_name}` : '未选择买家意向')
    : (selectedTarget ? selectedTarget.target_name : '未选择标的');

  return (
    <div className="h-[calc(100vh-7rem)] flex flex-col">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-gray-900">智能推荐</h1>
          <div className="flex items-center border border-gray-200 bg-white p-0.5">
            <button
              onClick={() => switchMode('buyer-to-target')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium transition-all ${
                mode === 'buyer-to-target' ? 'bg-brand-600 text-white' : 'text-gray-600 hover:text-brand-600'
              }`}
            >
              <ArrowRightLeft className="w-3.5 h-3.5" />
              为买家找标的
            </button>
            <button
              onClick={() => switchMode('target-to-buyer')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium transition-all ${
                mode === 'target-to-buyer' ? 'bg-brand-600 text-white' : 'text-gray-600 hover:text-brand-600'
              }`}
            >
              <ArrowRightLeft className="w-3.5 h-3.5" />
              为标的找买家
            </button>
          </div>
        </div>

        <div className="flex items-center gap-3 text-sm">
          <span className="text-gray-500">
            推荐 <span className="font-semibold text-gray-900">{items.length}</span> 项
          </span>
          <span className="text-gray-500">
            已加入 <span className="font-semibold text-emerald-700">{shortlistCount}</span> 项
          </span>
          <button
            disabled={shortlistCount === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 font-medium bg-brand-600 text-white hover:bg-brand-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            title={shortlistCount === 0 ? '请先将推荐项加入推荐列表' : ''}
          >
            <FileText className="w-3.5 h-3.5" />
            生成推荐报告
          </button>
          <button
            onClick={() => setConditionsOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 font-medium border border-gray-200 text-gray-700 hover:border-brand-500 hover:text-brand-600 transition-colors"
          >
            <Eye className="w-3.5 h-3.5" />
            查看条件
          </button>
        </div>
      </div>

      <div className="flex items-center gap-3 mb-3 bg-white border border-gray-200 px-4 py-2.5">
        <span className="text-xs text-gray-500">对象：</span>
        {mode === 'buyer-to-target' ? (
          <select
            value={selectedIntentId}
            onChange={(event) => handleSelectIntent(event.target.value)}
            className="text-sm border border-gray-200 px-2 py-1 bg-gray-50 focus:border-brand-500 outline-none min-w-[200px]"
          >
            <option value="">选择买家意向...</option>
            {intentsList.map((intent) => (
              <option key={intent.id} value={intent.id}>{intent.intent_name}</option>
            ))}
          </select>
        ) : (
          <select
            value={selectedTargetId}
            onChange={(event) => handleSelectTarget(event.target.value)}
            className="text-sm border border-gray-200 px-2 py-1 bg-gray-50 focus:border-brand-500 outline-none min-w-[200px]"
          >
            <option value="">选择标的...</option>
            {targetsList.map((target) => (
              <option key={target.id} value={target.id}>{target.target_name}</option>
            ))}
          </select>
        )}
        <span className="text-sm text-gray-700">{objectLabel}</span>
        <button
          onClick={() => generateCandidates('开始推荐')}
          disabled={generating || (mode === 'buyer-to-target' ? !selectedIntentId : !selectedTargetId)}
          className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-40"
        >
          {generating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
          开始推荐
        </button>
      </div>

      {deepEvalStatus === 'running' ? (
        <div className="mb-3 bg-amber-50 border border-amber-200 px-4 py-2 flex items-center gap-2">
          <Loader2 className="w-4 h-4 text-amber-600 shrink-0 animate-spin" />
          <span className="text-xs text-amber-700">
            AI 深度评估进行中（约 1 分钟）……当前列表为规则初排，评估完成后会自动重排并标注 A/B/C 评级与推荐理由。离开本页后可在工作台的推荐会话中查看结果。
          </span>
        </div>
      ) : deepEvalStatus === 'done' ? (
        <div className="mb-3 bg-emerald-50 border border-emerald-200 px-4 py-2 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
          <span className="text-xs text-emerald-700">AI 深度评估完成：已按评级重排，每个候选附评级与推荐理由。</span>
        </div>
      ) : deepEvalStatus === 'failed' ? (
        <div className="mb-3 bg-gray-50 border border-gray-200 px-4 py-2 flex items-center gap-2">
          <Info className="w-4 h-4 text-gray-500 shrink-0" />
          <span className="text-xs text-gray-600">AI 深度评估暂未完成，当前展示规则初排结果；稍后可在工作台的推荐会话中查看。</span>
        </div>
      ) : (
        <div className="mb-3 bg-emerald-50 border border-emerald-200 px-4 py-2 flex items-center gap-2">
          <Info className="w-4 h-4 text-emerald-600 shrink-0" />
          <span className="text-xs text-emerald-700">推荐先按结构化规则初排（秒出），随后 AI 深度评估自动重排并给出评级与理由。</span>
        </div>
      )}

      {generationError && (
        <div className="mb-3 bg-red-50 border border-red-200 px-4 py-2 text-xs text-red-700">
          {generationError}
        </div>
      )}

      <div className="flex-1 grid grid-cols-12 gap-4 min-h-0">
        <div className="col-span-7 bg-white border border-gray-200 flex flex-col min-h-0">
          <div className="px-4 py-3 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900">对话</h2>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {chatMessages.length === 0 && (
              <div className="border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
                <p className="font-medium text-gray-800 mb-1">
                  {mode === 'buyer-to-target'
                    ? selectedIntent ? '已加载买家意向条件。' : '请选择买家意向或输入需求。'
                    : selectedTarget ? `已加载标的：${selectedTarget.target_name}` : '请选择标的项目。'}
                </p>
                <p className="text-xs text-gray-500">可以直接点击“开始推荐”，也可以输入补充条件。</p>
              </div>
            )}
            {chatMessages.map((message, index) => (
              <div
                key={index}
                className={
                  message.role === 'user'
                    ? 'border-l-2 border-l-brand-600 bg-brand-50 px-4 py-3'
                    : 'border border-gray-200 bg-white px-4 py-3'
                }
              >
                <span className="text-xs font-medium text-gray-500 mb-1 block">
                  {message.role === 'user' ? '用户' : '系统'}
                </span>
                <p className="text-sm leading-relaxed text-gray-800 whitespace-pre-line">{message.content}</p>
              </div>
            ))}
          </div>
          <div className="p-3 border-t border-gray-100">
            <div className="flex items-center gap-2 border border-gray-200 focus-within:border-brand-600 transition-all">
              <input
                type="text"
                value={inputValue}
                onChange={(event) => setInputValue(event.target.value)}
                onKeyDown={(event) => event.key === 'Enter' && handleSend()}
                placeholder="输入“开始推荐”或补充推荐条件..."
                className="flex-1 px-4 py-2.5 text-sm outline-none placeholder:text-gray-400"
              />
              <button
                onClick={handleSend}
                className="mr-2 p-2 bg-brand-600 text-white hover:bg-brand-700 transition-colors disabled:opacity-40"
                disabled={!inputValue.trim() || generating}
              >
                {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>

        <div className="col-span-5 bg-white border border-gray-200 flex flex-col min-h-0">
          <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-900">
              推荐结果 <span className="text-gray-400 font-normal">{items.length} 项</span>
            </h2>
            {shortlistCount > 0 && (
              <span className="text-xs font-medium text-emerald-700">已加入 {shortlistCount} 项</span>
            )}
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {items.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center px-6">
                {generating ? <Loader2 className="w-8 h-8 text-gray-300 mb-3 animate-spin" /> : <Sparkles className="w-8 h-8 text-gray-300 mb-3" />}
                <p className="text-sm text-gray-400">{generating ? '正在生成推荐...' : '暂无推荐结果'}</p>
                <p className="text-xs text-gray-400 mt-1">选择对象并发送推荐请求后，结果将展示在此</p>
              </div>
            ) : (
              items.map((item, index) => (
                <RecommendationCard
                  key={item.id}
                  item={item}
                  index={index + 1}
                  onToggleShortlist={() => toggleShortlist(item.id)}
                />
              ))
            )}
          </div>
        </div>
      </div>

      {conditionsOpen && (
        <ConditionsDrawer
          mode={mode}
          intent={selectedIntent}
          target={selectedTarget}
          party={intentParty}
          onClose={() => setConditionsOpen(false)}
        />
      )}
    </div>
  );
}

function RecommendationCard({
  item,
  index,
  onToggleShortlist,
}: {
  item: RecommendationItem;
  index: number;
  onToggleShortlist: () => void;
}) {
  return (
    <div className={`border transition-all ${item.inShortlist ? 'border-emerald-300 bg-emerald-50/50' : 'border-gray-200 bg-white hover:border-brand-200'}`}>
      <div className="p-3 space-y-2">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-gray-400 w-4">{index}</span>
            <span className="text-sm font-semibold text-gray-900">{item.name}</span>
          </div>
          <span className="flex items-center gap-1">
            {item.deepEvalGrade && (
              <span
                className={`text-xs font-semibold px-2 py-0.5 border ${
                  item.deepEvalGrade === 'A'
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-300'
                    : item.deepEvalGrade === 'B'
                      ? 'bg-blue-50 text-blue-700 border-blue-200'
                      : 'bg-gray-50 text-gray-500 border-gray-200'
                }`}
              >
                {item.deepEvalGrade} 档
              </span>
            )}
            <span className="text-xs font-medium px-2 py-0.5 bg-brand-50 text-brand-700 border border-brand-200">
              {item.strength}
            </span>
          </span>
        </div>

        <div className="ml-6 text-xs text-gray-600 space-y-0.5">
          {item.deepEvalReason && <p className="text-gray-800 font-medium">AI 评估：{item.deepEvalReason}</p>}
          {item.matchSummary && <p className="text-emerald-700">匹配：{item.matchSummary}</p>}
          {item.gapSummary && <p className="text-amber-700">缺口：{item.gapSummary}</p>}
          {item.deepEvalRisks && item.deepEvalRisks !== '暂无' && <p className="text-amber-600">AI 风险提示：{item.deepEvalRisks}</p>}
          {item.riskSummary && <p className="text-gray-400">风险：{item.riskSummary}</p>}
        </div>

        <div className="ml-6">
          {item.inShortlist ? (
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-emerald-600 text-white">
                <CheckCircle2 className="w-3 h-3" />
                已加入推荐列表
              </span>
              <button onClick={onToggleShortlist} className="text-xs text-gray-500 hover:text-red-600">
                取消
              </button>
            </div>
          ) : (
            <button
              onClick={onToggleShortlist}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium border border-gray-200 text-gray-700 hover:border-brand-500 hover:text-brand-600 hover:bg-brand-50 transition-colors"
            >
              <Plus className="w-3 h-3" />
              加入推荐列表
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ConditionsDrawer({
  mode,
  intent,
  target,
  party,
  onClose,
}: {
  mode: Mode;
  intent: BuyerIntent | undefined;
  target: SellerTarget | undefined;
  party: BuyerParty | null;
  onClose: () => void;
}) {
  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <div className="fixed right-0 top-0 bottom-0 w-[400px] bg-white z-50 shadow-xl flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">
            {mode === 'buyer-to-target' ? '买家意向条件' : '标的条件'}
          </h2>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {mode === 'buyer-to-target' ? (
            intent ? (
              <>
                {party && (
                  <Section label="买家主体">
                    <p className="text-sm text-gray-800">{party.buyer_name}</p>
                  </Section>
                )}
                <Section label="Hard 条件">
                  <div className="space-y-2">
                    {intent.industry_primary && <ConditionRow icon={Building2} label="行业" value={intent.industry_primary} />}
                    {intent.region_scope_summary && <ConditionRow icon={MapPin} label="区域" value={intent.region_scope_summary} />}
                    {intent.min_net_profit_yuan && <ConditionRow icon={TrendingUp} label="利润" value={`>=${(Number(intent.min_net_profit_yuan) / 10000).toFixed(0)}万`} />}
                    {intent.max_pe && <ConditionRow icon={Star} label="PE" value={`<=${Number(intent.max_pe).toFixed(0)}`} />}
                    {intent.requires_consolidation && intent.requires_consolidation !== 'unknown' && (
                      <ConditionRow icon={CheckCircle2} label="并表" value={intent.requires_consolidation === 'yes' ? '需要' : '不需要'} />
                    )}
                  </div>
                </Section>
                {intent.preference_summary && <Section label="Preference"><p className="text-sm text-gray-600">{intent.preference_summary}</p></Section>}
                {intent.negative_summary && (
                  <Section label="排除项">
                    <div className="flex items-center gap-2 text-sm text-gray-600">
                      <Ban className="w-3.5 h-3.5 text-gray-400" />
                      <span>{intent.negative_summary}</span>
                    </div>
                  </Section>
                )}
                {intent.unknown_summary && <Section label="Unknown / 待确认"><p className="text-sm text-gray-600">{intent.unknown_summary}</p></Section>}
              </>
            ) : (
              <p className="text-sm text-gray-400">未选择买家意向</p>
            )
          ) : (
            target ? (
              <Section label="标的条件">
                <div className="space-y-2">
                  {target.industry_primary && <ConditionRow icon={Building2} label="行业" value={target.industry_primary} />}
                  {target.headquarter_province && <ConditionRow icon={MapPin} label="区域" value={`${target.headquarter_province} ${target.headquarter_city || ''}`} />}
                  {target.current_net_profit_yuan && <ConditionRow icon={TrendingUp} label="利润" value={`${(Number(target.current_net_profit_yuan) / 10000).toFixed(0)}万`} />}
                  {target.pe_ratio && <ConditionRow icon={Star} label="PE" value={Number(target.pe_ratio).toFixed(1)} />}
                </div>
              </Section>
            ) : (
              <p className="text-sm text-gray-400">未选择标的</p>
            )
          )}
        </div>
      </div>
    </>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">{label}</h3>
      {children}
    </div>
  );
}

function ConditionRow({ icon: Icon, label, value }: { icon: typeof Building2; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <Icon className="w-3.5 h-3.5 text-gray-400 shrink-0" />
      <span className="text-gray-500 w-10 shrink-0">{label}</span>
      <span className="text-gray-800">{value}</span>
    </div>
  );
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
  return [parts.join('\n'), '', '您可以：', '- 直接点击“开始推荐”使用现有条件', '- 输入补充条件覆盖或细化'].join('\n');
}

function buildTargetGuidance(target: SellerTarget): string {
  const parts: string[] = [`已加载标的：${target.target_name}`];
  if (target.industry_primary) parts.push(`行业：${target.industry_primary}`);
  if (target.headquarter_province) parts.push(`地区：${target.headquarter_province}${target.headquarter_city || ''}`);
  if (target.current_net_profit_yuan) parts.push(`利润：${(Number(target.current_net_profit_yuan) / 10000).toFixed(0)}万`);
  return [parts.join('\n'), '', '您可以：', '- 直接点击“开始推荐”为该标的匹配买家意向', '- 输入补充条件，例如“只看浙江买家”'].join('\n');
}

function mapCandidate(candidate: RecommendationCandidate, sessionId: string | null): RecommendationItem {
  const targetName = candidate.seller_target_name || '未命名标的';
  const intentName = candidate.buyer_intent_name || '未命名意向';
  const isBuyerMode = candidate.mode === 'buyer_to_target';
  return {
    id: `${candidate.mode}:${candidate.seller_target_id || ''}:${candidate.buyer_intent_id || ''}`,
    sessionId,
    mode: candidate.mode,
    sellerTargetId: candidate.seller_target_id,
    buyerIntentId: candidate.buyer_intent_id,
    buyerPartyId: candidate.buyer_party_id,
    name: isBuyerMode ? targetName : `${candidate.buyer_name || '未绑定买家'} / ${intentName}`,
    strength: levelLabel(candidate.recommendation_level, candidate.score),
    matchSummary: candidate.match_summary,
    gapSummary: candidate.gap_summary || '',
    riskSummary: candidate.risk_summary,
    evidence: candidate.evidence_json,
    deepEvalGrade: candidate.deep_eval?.grade || null,
    deepEvalReason: candidate.deep_eval?.reason || null,
    deepEvalRisks: candidate.deep_eval?.risks || null,
    inShortlist: false,
    persisted: false,
    selectedItemId: null,
  };
}

function levelLabel(level: RecommendationCandidate['recommendation_level'], score: number): string {
  const labels: Record<RecommendationCandidate['recommendation_level'], string> = {
    strong: '强推荐',
    recommended: '推荐',
    possible: '可关注',
    weak: '弱匹配',
  };
  return `${labels[level]} ${Math.round(score)}`;
}

function levelToApi(label: string): RecommendationCandidate['recommendation_level'] {
  if (label.includes('强推荐')) return 'strong';
  if (label.includes('可关注')) return 'possible';
  if (label.includes('弱匹配')) return 'weak';
  return 'recommended';
}
