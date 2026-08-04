import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { attachments, buyerIntents, recommendations } from '../lib/api';
import type {
  RecommendationAgentBrief,
  RecommendationAgentQuestion,
  RecommendationAgentSearchStep,
  RecommendationMessage,
} from '../types/api';
import AgentComposer, { AGENT_INPUT_MAX_CHARS, type RecommendMode } from '../features/recommend/AgentComposer';
import AgentTurnView, { type AgentTurnState } from '../features/recommend/AgentTurnView';
import SessionPicker from '../features/recommend/SessionPicker';

const POLL_INTERVAL_MS = 1200;
// Agent 的墙钟预算是 240s；这里留到 6 分钟，够覆盖排队等待再判失败。
const POLL_MAX_ATTEMPTS = 300;
const OCR_POLL_INTERVAL_MS = 2500;
const OCR_POLL_MAX_ATTEMPTS = 60;

export default function Recommend() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [mode, setMode] = useState<RecommendMode>('buyer_to_target');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turns, setTurns] = useState<AgentTurnState[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [fileBusy, setFileBusy] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const [pendingFileText, setPendingFileText] = useState<string>('');
  const [prefill, setPrefill] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement | null>(null);
  const pollRef = useRef<number | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const bootstrappedRef = useRef(false);

  const activeTurn = turns[turns.length - 1] || null;
  const busy = Boolean(activeTurn && !activeTurn.answerDone && !activeTurn.failed && !activeTurn.question);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => () => {
    stopPolling();
    streamAbortRef.current?.abort();
  }, [stopPolling]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turns.length, activeTurn?.answer]);

  const patchTurn = useCallback((turnId: string, patch: Partial<AgentTurnState>) => {
    setTurns((prev) => prev.map((turn) => (turn.turnId === turnId ? { ...turn, ...patch } : turn)));
  }, []);

  /** Stream the write-up. Resumable: the endpoint replays a persisted answer. */
  const streamAnswer = useCallback(async (activeSessionId: string, turnId: string) => {
    streamAbortRef.current?.abort();
    const controller = new AbortController();
    streamAbortRef.current = controller;
    patchTurn(turnId, { streaming: true });
    let accumulated = '';
    try {
      for await (const event of recommendations.answerStream(activeSessionId, turnId, { signal: controller.signal })) {
        if (event.event === 'delta') {
          accumulated += String(event.data.text || '');
          patchTurn(turnId, { answer: accumulated });
        } else if (event.event === 'done') {
          // done 带的是回填过链接的最终正文，覆盖流式累积的裸文本。
          patchTurn(turnId, {
            answer: String(event.data.markdown || accumulated),
            answerDone: true,
            streaming: false,
          });
          return;
        } else if (event.event === 'error') {
          patchTurn(turnId, { failed: `生成回答失败：${String(event.data.message || '未知错误')}` });
        }
      }
      patchTurn(turnId, { answerDone: true, streaming: false });
    } catch (streamError) {
      if (controller.signal.aborted) return;
      patchTurn(turnId, {
        streaming: false,
        failed: streamError instanceof Error ? streamError.message : '回答流中断',
      });
    }
  }, [patchTurn]);

  const applyMessages = useCallback((turnId: string, messages: RecommendationMessage[]) => {
    const steps: RecommendationAgentSearchStep[] = [];
    let question: RecommendationAgentQuestion | null = null;
    let brief: RecommendationAgentBrief | null = null;

    for (const message of messages) {
      const metadata = (message.metadata_json || {}) as Record<string, unknown>;
      if (String(metadata.turn_id || '') !== turnId) continue;
      if (message.content_type !== 'json') continue;
      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(message.content) as Record<string, unknown>;
      } catch {
        continue;
      }
      const messageType = String(metadata.message_type || payload.message_type || '');
      if (messageType === 'agent_step' && payload.step) {
        steps.push(payload.step as RecommendationAgentSearchStep);
      } else if (messageType === 'agent_question' && payload.question) {
        question = payload.question as RecommendationAgentQuestion;
      } else if (messageType === 'agent_brief' && payload.brief) {
        brief = payload.brief as RecommendationAgentBrief;
      }
    }
    return { steps, question, brief };
  }, []);

  const startPolling = useCallback((activeSessionId: string, turnId: string) => {
    stopPolling();
    let attempts = 0;
    const startedAt = Date.now();
    pollRef.current = window.setInterval(async () => {
      attempts += 1;
      patchTurn(turnId, { elapsedSeconds: Math.floor((Date.now() - startedAt) / 1000) });
      if (attempts > POLL_MAX_ATTEMPTS) {
        stopPolling();
        patchTurn(turnId, { failed: '这一轮超时了。可以重试，或换个更具体的说法。' });
        return;
      }
      try {
        const messages = await recommendations.messages(activeSessionId, { limit: 500 });
        const { steps, question, brief } = applyMessages(turnId, messages);
        patchTurn(turnId, { steps });
        if (question) {
          stopPolling();
          patchTurn(turnId, { question, answerDone: true });
          return;
        }
        if (brief) {
          stopPolling();
          patchTurn(turnId, { followUps: brief.follow_up_suggestions || [] });
          void streamAnswer(activeSessionId, turnId);
        }
      } catch {
        // 轮询期间的网络抖动不该终止整轮，由 attempts 上限兜底。
      }
    }, POLL_INTERVAL_MS);
  }, [applyMessages, patchTurn, stopPolling, streamAnswer]);

  const send = useCallback(async (message: string) => {
    setError(null);
    try {
      const turn = await recommendations.agentTurn({
        mode: 'buyer_to_target',
        session_id: sessionId || undefined,
        user_message: message,
      });
      if (!sessionId) {
        setSessionId(turn.session_id);
        const next = new URLSearchParams(searchParams);
        next.set('session', turn.session_id);
        setSearchParams(next, { replace: true });
      }
      setPendingFileText('');
      setFileName(null);
      setTurns((prev) => [
        ...prev,
        {
          turnId: turn.turn_id,
          userMessage: message,
          steps: [],
          question: null,
          followUps: [],
          answer: '',
          answerDone: false,
          streaming: false,
          failed: null,
          elapsedSeconds: 0,
        },
      ]);
      startPolling(turn.session_id, turn.turn_id);
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : '发送失败');
    }
  }, [searchParams, sessionId, setSearchParams, startPolling]);

  const handleSubmit = useCallback((message: string) => {
    const combined = pendingFileText
      ? `${message}\n\n【附件正文】\n${pendingFileText}`.slice(0, AGENT_INPUT_MAX_CHARS)
      : message;
    void send(combined);
  }, [pendingFileText, send]);

  /**
   * Read a requirement document without creating anything.
   *
   * The upload is entity-free on purpose (`entity_type` omitted): the whole
   * point of this page is that no buyer intent or target has to exist yet.
   */
  const handleFile = useCallback(async (file: File) => {
    setFileBusy(true);
    setError(null);
    try {
      const uploaded = await attachments.uploadUnbound(file);
      const attachmentId = uploaded.attachment.id;
      let text = '';
      for (let attempt = 0; attempt < OCR_POLL_MAX_ATTEMPTS; attempt += 1) {
        const status = await attachments.ocrStatus(attachmentId);
        const parseStatus = String(status.latest_parsed_document?.parse_status || '');
        const jobStatus = String(status.latest_job?.status || '');
        if (parseStatus === 'parsed') {
          const extracted = await attachments.extractedText(attachmentId, { max_chars: AGENT_INPUT_MAX_CHARS });
          text = extracted.text;
          break;
        }
        if (jobStatus === 'failed' || parseStatus === 'failed') break;
        await new Promise((resolve) => window.setTimeout(resolve, OCR_POLL_INTERVAL_MS));
      }
      if (!text.trim()) {
        setError('没能从这个文件里读出正文，可以直接把需求粘贴到输入框。');
        return;
      }
      setPendingFileText(text.slice(0, AGENT_INPUT_MAX_CHARS));
      setFileName(file.name);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : '读取文件失败');
    } finally {
      setFileBusy(false);
    }
  }, []);

  const startNewConversation = useCallback(() => {
    stopPolling();
    streamAbortRef.current?.abort();
    setSessionId(null);
    setTurns([]);
    setError(null);
    setPendingFileText('');
    setFileName(null);
    setSearchParams(new URLSearchParams(), { replace: true });
  }, [setSearchParams, stopPolling]);

  const restoreSession = useCallback(async (restoreId: string) => {
    try {
      const messages = await recommendations.messages(restoreId, { limit: 500 });
      setSessionId(restoreId);
      setTurns(rebuildTurns(messages));
    } catch {
      setError('恢复对话失败，可能已被删除');
    }
  }, []);

  /**
   * `?intentId=` comes from the buyer-intent list's 「推荐标的」 button.
   * The page starts from text now, so the intent is used to prefill the box
   * rather than to anchor the session — the consultant can still edit it
   * before sending, and nothing is created either way.
   */
  const prefillFromIntent = useCallback(async (intentId: string) => {
    try {
      const intent = await buyerIntents.get(intentId);
      const parts = [
        intent.raw_requirement_text || intent.intent_summary || '',
        intent.buyer_name ? `买家：${intent.buyer_name}` : '',
      ].filter(Boolean);
      setPrefill(parts.join('\n\n') || `按「${intent.intent_name}」的条件找标的`);
    } catch {
      setError('加载买家需求失败，可以直接在输入框描述需求');
    }
  }, []);

  useEffect(() => {
    if (bootstrappedRef.current) return;
    bootstrappedRef.current = true;
    const sessionParam = searchParams.get('session');
    const intentParam = searchParams.get('intentId');
    if (sessionParam) void restoreSession(sessionParam);
    else if (intentParam) void prefillFromIntent(intentParam);
  }, [prefillFromIntent, restoreSession, searchParams]);

  const openSession = (pickId: string) => {
    stopPolling();
    streamAbortRef.current?.abort();
    setTurns([]);
    const next = new URLSearchParams();
    next.set('session', pickId);
    setSearchParams(next);
    void restoreSession(pickId);
  };

  const empty = turns.length === 0;

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h1 className="text-lg font-semibold text-gray-900">智能推荐</h1>
        <div className="flex items-center gap-2">
          <SessionPicker onPick={openSession} />
          <button
            type="button"
            onClick={startNewConversation}
            className="border border-gray-200 px-3 py-1.5 text-sm font-medium text-gray-700 hover:border-brand-500 hover:text-brand-600"
          >
            新对话
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-2 border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
      )}

      {empty ? (
        <div className="flex flex-1 flex-col items-center justify-center px-4">
          <p className="mb-5 text-base text-gray-500">来了个需求？直接说，我来找。</p>
          <div className="w-full max-w-2xl">
            <AgentComposer
              mode={mode}
              onModeChange={setMode}
              locked={false}
              busy={busy}
              autoFocus
              placeholder="客户想收华东的精密制造，净利 2000 万以上，要能控股，PE 不超 12"
              onSubmit={handleSubmit}
              onPickFile={(file) => void handleFile(file)}
              fileBusy={fileBusy}
              fileName={fileName}
              onNewConversation={startNewConversation}
              prefill={prefill}
            />
          </div>
        </div>
      ) : (
        <>
          <div className="flex-1 space-y-6 overflow-y-auto pr-1">
            {turns.map((turn) => (
              <AgentTurnView
                key={turn.turnId}
                turn={turn}
                onSendSuggestion={(text) => void send(text)}
                onRetry={() => void send(turn.userMessage)}
              />
            ))}
            <div ref={bottomRef} />
          </div>
          <div className="mt-3">
            <AgentComposer
              mode={mode}
              onModeChange={setMode}
              locked
              busy={busy}
              placeholder="继续说…"
              onSubmit={handleSubmit}
              onPickFile={(file) => void handleFile(file)}
              fileBusy={fileBusy}
              fileName={fileName}
              onNewConversation={startNewConversation}
            />
          </div>
        </>
      )}
    </div>
  );
}

/** Replay a stored conversation. Answers are persisted, so nothing re-runs. */
function rebuildTurns(messages: RecommendationMessage[]): AgentTurnState[] {
  const byTurn = new Map<string, AgentTurnState>();
  const ensure = (turnId: string): AgentTurnState => {
    const existing = byTurn.get(turnId);
    if (existing) return existing;
    const created: AgentTurnState = {
      turnId,
      userMessage: '',
      steps: [],
      question: null,
      followUps: [],
      answer: '',
      answerDone: true,
      streaming: false,
      failed: null,
      elapsedSeconds: 0,
    };
    byTurn.set(turnId, created);
    return created;
  };

  let pendingUserMessage = '';
  for (const message of messages) {
    const metadata = (message.metadata_json || {}) as Record<string, unknown>;
    const turnId = String(metadata.turn_id || '');
    if (message.role === 'user') {
      pendingUserMessage = message.content;
      continue;
    }
    if (!turnId || message.content_type !== 'json') continue;
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(message.content) as Record<string, unknown>;
    } catch {
      continue;
    }
    const turn = ensure(turnId);
    if (!turn.userMessage && pendingUserMessage) {
      turn.userMessage = pendingUserMessage;
      pendingUserMessage = '';
    }
    const messageType = String(metadata.message_type || payload.message_type || '');
    if (messageType === 'agent_step' && payload.step) {
      turn.steps.push(payload.step as RecommendationAgentSearchStep);
    } else if (messageType === 'agent_question' && payload.question) {
      turn.question = payload.question as RecommendationAgentQuestion;
    } else if (messageType === 'agent_brief' && payload.brief) {
      turn.followUps = (payload.brief as RecommendationAgentBrief).follow_up_suggestions || [];
    } else if (messageType === 'agent_answer') {
      turn.answer = String(payload.markdown || '');
    }
  }
  return [...byTurn.values()];
}
