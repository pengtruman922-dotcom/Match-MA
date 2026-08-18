import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { attachments as attachmentsApi, buyerIntents, recommendations } from '../lib/api';
import type {
  AttachmentUploadPolicy,
  RecommendationAgentBrief,
  RecommendationAgentQuestion,
  RecommendationAgentSearchStep,
  RecommendationMessage,
} from '../types/api';
import { formatBytes } from '../lib/format';
import AgentComposer, { AGENT_INPUT_MAX_CHARS, type RecommendMode } from '../features/recommend/AgentComposer';
import AgentTurnView, { type AgentTurnState } from '../features/recommend/AgentTurnView';
import IntentPicker from '../features/recommend/IntentPicker';
import SessionPicker from '../features/recommend/SessionPicker';
import { intentToRequirementText } from '../features/recommend/intentSummary';

const POLL_INTERVAL_MS = 1200;
// Agent 的墙钟预算是 240s；这里留到 6 分钟，够覆盖排队等待再判失败。
const POLL_MAX_ATTEMPTS = 300;
const OCR_POLL_INTERVAL_MS = 2500;
const OCR_POLL_MAX_ATTEMPTS = 60;
/** 后端 AGENT_MAX_IMAGE_ATTACHMENTS 的镜像。 */
const MAX_IMAGE_ATTACHMENTS = 6;
const DOCUMENT_EXTENSIONS = ['.pdf', '.doc', '.docx', '.txt', '.md', '.xlsx', '.xls', '.csv'];
const IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp'];

interface PendingAttachment {
  key: string;
  name: string;
  kind: 'document' | 'image' | 'requirement';
  status: 'reading' | 'ready' | 'failed';
  error?: string;
  /** 文档正文 / 带入的需求正文。发送时拼进消息，不进输入框。 */
  text?: string;
  /** 图片：交给多模态模型的附件 id。 */
  attachmentId?: string;
}

/** 带进来的需求只留一条：一轮对话服务一个买家，两份条件只会被搅成一锅。 */
const REQUIREMENT_KEY = 'requirement';

function isImageFile(file: File): boolean {
  if (file.type.startsWith('image/')) return true;
  const name = file.name.toLowerCase();
  return IMAGE_EXTENSIONS.some((extension) => name.endsWith(extension));
}

export default function Recommend() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [mode, setMode] = useState<RecommendMode>('buyer_to_target');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turns, setTurns] = useState<AgentTurnState[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [uploadPolicy, setUploadPolicy] = useState<AttachmentUploadPolicy | null>(null);
  const [stopping, setStopping] = useState(false);

  const bottomRef = useRef<HTMLDivElement | null>(null);
  const pollRef = useRef<number | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const bootstrappedRef = useRef(false);

  const activeTurn = turns[turns.length - 1] || null;
  const busy = Boolean(
    activeTurn && !activeTurn.answerDone && !activeTurn.failed && !activeTurn.question && !activeTurn.aborted,
  );

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
            failed: null,
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
    let aborted = false;

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
      } else if (messageType === 'agent_aborted') {
        aborted = true;
      }
    }
    return { steps, question, brief, aborted };
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
        // 任务状态和消息一起看：任务挂掉时一条消息都不会写，光看消息表只会
        // 一直转到自己的超时，用户永远不知道为什么。
        const [messages, status] = await Promise.all([
          recommendations.messages(activeSessionId, { limit: 500 }),
          recommendations.turnStatus(activeSessionId, turnId).catch(() => null),
        ]);
        const { steps, question, brief, aborted } = applyMessages(turnId, messages);
        patchTurn(turnId, { steps });
        if (status?.failed && !aborted) {
          stopPolling();
          patchTurn(turnId, {
            failed: status.error_message || '这一轮没能跑完。',
            answerDone: true,
            streaming: false,
          });
          return;
        }
        if (aborted) {
          // 另一个页签把这一轮停了。
          stopPolling();
          patchTurn(turnId, { aborted: true, answerDone: true, streaming: false });
          return;
        }
        if (question) {
          stopPolling();
          patchTurn(turnId, { question, answerDone: true });
          return;
        }
        if (brief) {
          stopPolling();
          patchTurn(turnId, { followUps: normalizeBriefFollowUps(brief.follow_up_suggestions) });
          void streamAnswer(activeSessionId, turnId);
        }
      } catch {
        // 轮询期间的网络抖动不该终止整轮，由 attempts 上限兜底。
      }
    }, POLL_INTERVAL_MS);
  }, [applyMessages, patchTurn, stopPolling, streamAnswer]);

  const send = useCallback(async (message: string, attachmentIds: string[] = []) => {
    setError(null);
    try {
      const turn = await recommendations.agentTurn({
        mode: 'buyer_to_target',
        session_id: sessionId || undefined,
        user_message: message,
        attachment_ids: attachmentIds,
      });
      if (!sessionId) {
        setSessionId(turn.session_id);
        const next = new URLSearchParams(searchParams);
        next.set('session', turn.session_id);
        setSearchParams(next, { replace: true });
      }
      setAttachments([]);
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
          aborted: false,
          elapsedSeconds: 0,
        },
      ]);
      startPolling(turn.session_id, turn.turn_id);
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : '发送失败');
    }
  }, [searchParams, sessionId, setSearchParams, startPolling]);

  /**
   * Stop the turn in flight.
   *
   * The marker is written server-side first and everything local follows from
   * it, so a stop survives the tab closing a second later — the worker notices
   * at its next checkpoint whether or not this page is still here.
   */
  const stopActiveTurn = useCallback(async () => {
    if (!sessionId || !activeTurn || stopping) return;
    setStopping(true);
    try {
      await recommendations.abortTurn(sessionId, activeTurn.turnId);
      stopPolling();
      streamAbortRef.current?.abort();
      patchTurn(activeTurn.turnId, {
        aborted: true,
        answer: '',
        followUps: [],
        failed: null,
        answerDone: true,
        streaming: false,
      });
    } catch (abortError) {
      setError(abortError instanceof Error ? abortError.message : '停止失败，请重试');
    } finally {
      setStopping(false);
    }
  }, [activeTurn, patchTurn, sessionId, stopPolling, stopping]);

  const handleSubmit = useCallback((message: string) => {
    const ready = attachments.filter((item) => item.status === 'ready');
    const requirement = ready.find((item) => item.kind === 'requirement');
    const documentText = ready
      .filter((item) => item.kind === 'document' && item.text)
      .map((item) => `【${item.name}】\n${item.text}`)
      .join('\n\n');
    const combined = [
      requirement?.text ? `【已有买家需求：${requirement.name}】\n${requirement.text}` : '',
      message,
      documentText ? `【附件正文】\n${documentText}` : '',
    ]
      .filter(Boolean)
      .join('\n\n')
      .slice(0, AGENT_INPUT_MAX_CHARS);
    if (!combined.trim()) return;
    const imageIds = ready
      .filter((item) => item.kind === 'image' && item.attachmentId)
      .map((item) => item.attachmentId as string);
    void send(combined, imageIds);
  }, [attachments, send]);

  const patchAttachment = useCallback((key: string, patch: Partial<PendingAttachment>) => {
    setAttachments((prev) => prev.map((item) => (item.key === key ? { ...item, ...patch } : item)));
  }, []);

  const removeAttachment = useCallback((key: string) => {
    setAttachments((prev) => prev.filter((item) => item.key !== key));
  }, []);

  /**
   * Take in a requirement file without creating anything.
   *
   * The upload is entity-free on purpose (`entity_type` omitted): the whole
   * point of this page is that no buyer intent or target has to exist yet.
   *
   * Documents and images take different routes because the platform reads them
   * differently — a document goes through OCR and its text lands in the box
   * where the consultant can check and edit it, while an image has no text to
   * preview and goes to the multimodal model as-is.
   */
  const handleFile = useCallback(async (file: File) => {
    setError(null);
    const maxBytes = uploadPolicy?.max_upload_bytes || 25 * 1024 * 1024;
    const key = `${file.name}:${file.size}:${file.lastModified}:${Math.random().toString(36).slice(2, 8)}`;
    const image = isImageFile(file);

    if (file.size > maxBytes) {
      setError(`${file.name} 超过 ${formatBytes(maxBytes)}。`);
      return;
    }
    if (image && attachments.filter((item) => item.kind === 'image').length >= MAX_IMAGE_ATTACHMENTS) {
      setError(`一次最多带 ${MAX_IMAGE_ATTACHMENTS} 张图片。`);
      return;
    }

    setAttachments((prev) => [
      ...prev,
      { key, name: file.name, kind: image ? 'image' : 'document', status: 'reading' },
    ]);

    try {
      // 图片不进 OCR：平台的策略是图片直接交给多模态模型，OCR 节点对图片只会
      // 返回 skipped。
      const uploaded = await attachmentsApi.uploadUnbound(file, { autoStartOcr: !image });
      const attachmentId = uploaded.attachment.id;
      if (image) {
        patchAttachment(key, { status: 'ready', attachmentId });
        return;
      }

      let text = '';
      let failure = '没能从这个文件里读出正文，可以直接把需求粘贴到输入框。';
      for (let attempt = 0; attempt < OCR_POLL_MAX_ATTEMPTS; attempt += 1) {
        const status = await attachmentsApi.ocrStatus(attachmentId);
        const parseStatus = String(status.latest_parsed_document?.parse_status || '');
        const jobStatus = String(status.latest_job?.status || '');
        if (parseStatus === 'parsed') {
          const extracted = await attachmentsApi.extractedText(attachmentId, {
            max_chars: AGENT_INPUT_MAX_CHARS,
          });
          text = extracted.text;
          break;
        }
        // skipped 是「这个类型解析不了」的终态，不是中间状态 —— 早期版本没认它，
        // 于是空转满 60 次才报错。
        if (parseStatus === 'skipped') {
          failure = '这个文件类型读不出正文。';
          break;
        }
        if (jobStatus === 'failed' || parseStatus === 'failed') break;
        await new Promise((resolve) => window.setTimeout(resolve, OCR_POLL_INTERVAL_MS));
      }
      if (!text.trim()) {
        patchAttachment(key, { status: 'failed', error: failure });
        return;
      }
      patchAttachment(key, { status: 'ready', text: text.slice(0, AGENT_INPUT_MAX_CHARS) });
    } catch (uploadError) {
      patchAttachment(key, {
        status: 'failed',
        error: uploadError instanceof Error ? uploadError.message : '读取失败',
      });
    }
  }, [attachments, patchAttachment, uploadPolicy]);

  const startNewConversation = useCallback(() => {
    stopPolling();
    streamAbortRef.current?.abort();
    setSessionId(null);
    setTurns([]);
    setError(null);
    setAttachments([]);
    setSearchParams(new URLSearchParams(), { replace: true });
  }, [setSearchParams, stopPolling]);

  const restoreSession = useCallback(async (restoreId: string) => {
    let resumeTurnIds: string[] = [];
    try {
      const messages = await recommendations.messages(restoreId, { limit: 500 });
      const rebuilt = rebuildTurns(messages);
      resumeTurnIds = rebuilt.resumeTurnIds;
      setSessionId(restoreId);
      setTurns(rebuilt.turns);
    } catch {
      setError('恢复对话失败，可能已被删除');
      return;
    }
    // 正文只在 SSE 的 done 事件里落库，所以关页签会留下「素材齐了、正文没写」
    // 的轮次。端点在首次连接时就会生成并落库，补连一次即可收尾——不补的话
    // 那一轮永远是个空气泡。
    for (const turnId of resumeTurnIds) {
      await streamAnswer(restoreId, turnId);
    }
  }, [streamAnswer]);

  /**
   * `?intentId=` comes from the buyer-intent list's 「推荐标的」 button.
   * The page starts from text now, so the intent is used to prefill the box
   * rather than to anchor the session — the consultant can still edit it
   * before sending, and nothing is created either way.
   */
  /**
   * Bring an existing buyer intent in as a chip, not as text in the box.
   *
   * Dumping the requirement into the textarea buries whatever the consultant
   * wanted to add underneath it. As a chip the box stays theirs, and the full
   * requirement rides along on send — the same route a document's text takes.
   */
  const attachIntent = useCallback(async (intentId: string) => {
    setError(null);
    setAttachments((prev) => [
      ...prev.filter((item) => item.kind !== 'requirement'),
      { key: REQUIREMENT_KEY, name: '正在读取买家需求…', kind: 'requirement', status: 'reading' },
    ]);
    try {
      const intent = await buyerIntents.get(intentId);
      const text = intentToRequirementText(intent);
      if (!text.trim()) {
        patchAttachment(REQUIREMENT_KEY, {
          name: intent.intent_name,
          status: 'failed',
          error: '这条需求还没有可用信息',
        });
        return;
      }
      patchAttachment(REQUIREMENT_KEY, {
        name: intent.intent_name,
        status: 'ready',
        text,
      });
    } catch {
      patchAttachment(REQUIREMENT_KEY, { status: 'failed', error: '加载失败' });
    }
  }, [patchAttachment]);

  useEffect(() => {
    attachmentsApi.uploadPolicy().then(setUploadPolicy).catch(() => {
      // 拿不到策略就退回内置默认值，附件按钮不该因此不可用。
      setUploadPolicy(null);
    });
  }, []);

  useEffect(() => {
    if (bootstrappedRef.current) return;
    bootstrappedRef.current = true;
    const sessionParam = searchParams.get('session');
    const intentParam = searchParams.get('intentId');
    if (sessionParam) void restoreSession(sessionParam);
    else if (intentParam) void attachIntent(intentParam);
  }, [attachIntent, restoreSession, searchParams]);

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
  const accept = [...DOCUMENT_EXTENSIONS, ...IMAGE_EXTENSIONS].join(',');
  const policyHint = uploadPolicy
    ? `单文件 ${uploadPolicy.max_upload_mb} MB 以内；文档读正文，图片直接给模型看`
    : null;
  const composerAttachments = attachments.map(({ key, name, kind, status, error: itemError, text }) => ({
    key,
    name,
    kind,
    status,
    error: itemError,
    // 文档和需求都能点开看要发出去的原文；图片没有正文可看。
    preview: kind === 'image' ? undefined : text,
  }));

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

      {/* 输入框永远贴底，空态上方就留白：位置不该随对话有没有开始而跳。 */}
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
          locked={!empty}
          busy={busy}
          autoFocus={empty}
          placeholder={
            empty ? '客户想收华东的精密制造，净利 2000 万以上，要能控股，PE 不超 12' : '继续说…'
          }
          onSubmit={handleSubmit}
          onStop={() => void stopActiveTurn()}
          stopping={stopping}
          onPickFile={(file) => void handleFile(file)}
          attachments={composerAttachments}
          onRemoveAttachment={removeAttachment}
          accept={accept}
          policyHint={policyHint}
          onNewConversation={startNewConversation}
          sourcePicker={
            mode === 'buyer_to_target' ? (
              <IntentPicker onPick={(intentId) => void attachIntent(intentId)} />
            ) : null
          }
        />
      </div>
    </div>
  );
}

interface RebuiltConversation {
  turns: AgentTurnState[];
  /** 素材齐了但正文没落库的轮次，交给调用方补连一次 SSE。 */
  resumeTurnIds: string[];
}

/**
 * Replay a stored conversation.
 *
 * Three end states have to be told apart, because they look identical in the
 * message table if you only ask "is there an answer": a turn that finished, a
 * turn whose brief landed but whose write-up never ran (the reader went away
 * mid-stream), and a turn the worker never got to at all.
 */
function rebuildTurns(messages: RecommendationMessage[]): RebuiltConversation {
  const byTurn = new Map<string, AgentTurnState>();
  const landed = new Map<string, { brief: boolean; answer: boolean }>();
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
      aborted: false,
      elapsedSeconds: 0,
    };
    byTurn.set(turnId, created);
    landed.set(turnId, { brief: false, answer: false });
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
      turn.followUps = normalizeBriefFollowUps(
        (payload.brief as RecommendationAgentBrief).follow_up_suggestions,
      );
      landed.get(turnId)!.brief = true;
    } else if (messageType === 'agent_answer') {
      turn.answer = String(payload.markdown || '');
      landed.get(turnId)!.answer = true;
    } else if (messageType === 'agent_aborted') {
      turn.aborted = true;
    }
  }

  // 循环结束还挂着一条用户消息 = 那一轮在排队时就被关掉了，worker 一条消息都
  // 没写过。仍然把提问显示出来，否则用户问过的话会凭空消失。
  if (pendingUserMessage.trim()) {
    const orphan = ensure(`orphan:${byTurn.size}`);
    orphan.userMessage = pendingUserMessage;
  }

  const turns = [...byTurn.values()];
  const resumeTurnIds: string[] = [];
  for (const turn of turns) {
    const flags = landed.get(turn.turnId) || { brief: false, answer: false };
    // 中止是终态：不续接、不报失败、不重试。素材落没落库都不再往下走。
    if (turn.aborted) continue;
    if (flags.answer || turn.question) continue;
    if (flags.brief) {
      turn.answerDone = false;
      resumeTurnIds.push(turn.turnId);
      continue;
    }
    turn.failed = '这一轮没有跑完。';
  }
  return { turns, resumeTurnIds };
}

/** The backend is authoritative; this is the display boundary for old stored briefs. */
function normalizeBriefFollowUps(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const values: string[] = [];
  for (const item of raw) {
    const suggestion = String(item || '').trim().slice(0, 80);
    if (suggestion && !values.includes(suggestion)) values.push(suggestion);
    if (values.length >= 4) break;
  }
  return values;
}
