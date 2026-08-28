import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { attachments as attachmentsApi, buyerIntents, recommendations } from '../lib/api';
import type {
  AttachmentUploadPolicy,
  RecommendationAgentBrief,
  RecommendationAgentQuestion,
  RecommendationAgentSearchStep,
  RecommendationAgentTurnProgress,
  RecommendationMessage,
} from '../types/api';
import { formatBytes } from '../lib/format';
import AgentComposer, { AGENT_INPUT_MAX_CHARS, type RecommendMode } from '../features/recommend/AgentComposer';
import AgentTurnView, { type AgentTurnState } from '../features/recommend/AgentTurnView';
import IntentPicker from '../features/recommend/IntentPicker';
import SessionPicker from '../features/recommend/SessionPicker';
import { intentToRequirementText } from '../features/recommend/intentSummary';
import {
  countRetryAttempts,
  POLL_UNREACHABLE_AFTER,
  pollDelayMs,
} from '../features/recommend/turnPolling';

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
  /**
   * 这一轮锚定的买家需求。带需求进来时才有值。
   *
   * 以前 `?intentId=` 只被拿来预填输入框，会话本身是匿名的 —— 于是深评拿不到
   * 买方自身情况，「与现有业务有关联性」这类要求只能判「无法判断」。现在它跟着
   * 请求一起走，会话记得住这一轮是给谁做的。
   */
  const [anchorIntentId, setAnchorIntentId] = useState<string | null>(null);
  const [uploadPolicy, setUploadPolicy] = useState<AttachmentUploadPolicy | null>(null);
  const [stopping, setStopping] = useState(false);

  const bottomRef = useRef<HTMLDivElement | null>(null);
  const pollTimerRef = useRef<number | null>(null);
  // 单飞的取消令牌。清掉 setTimeout 还不够：一次请求可能正在途中，
  // 它回来之后不能再排下一次。
  const pollTokenRef = useRef(0);
  // 秒表独立于轮询：轮询最慢到 30 秒一次，计时显示不能跟着一跳一跳。
  // 它只改本地数字，不发请求。
  const elapsedTimerRef = useRef<number | null>(null);
  const writerTimerRef = useRef<number | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const bootstrappedRef = useRef(false);

  const activeTurn = turns[turns.length - 1] || null;
  const busy = Boolean(
    activeTurn && !activeTurn.answerDone && !activeTurn.failed && !activeTurn.question && !activeTurn.aborted,
  );

  const stopPolling = useCallback(() => {
    pollTokenRef.current += 1;
    if (pollTimerRef.current) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (elapsedTimerRef.current) {
      window.clearInterval(elapsedTimerRef.current);
      elapsedTimerRef.current = null;
    }
  }, []);

  const stopWriterTimer = useCallback(() => {
    if (writerTimerRef.current) {
      window.clearInterval(writerTimerRef.current);
      writerTimerRef.current = null;
    }
  }, []);

  useEffect(() => () => {
    stopPolling();
    stopWriterTimer();
    streamAbortRef.current?.abort();
  }, [stopPolling, stopWriterTimer]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turns.length, activeTurn?.answer]);

  const patchTurn = useCallback((turnId: string, patch: Partial<AgentTurnState>) => {
    setTurns((prev) => prev.map((turn) => (turn.turnId === turnId ? { ...turn, ...patch } : turn)));
  }, []);

  /** Stream the write-up. Resumable: the endpoint replays a persisted answer. */
  const streamAnswer = useCallback(async (activeSessionId: string, turnId: string) => {
    streamAbortRef.current?.abort();
    stopWriterTimer();
    const controller = new AbortController();
    streamAbortRef.current = controller;
    const writerStartedAt = Date.now();
    patchTurn(turnId, { streaming: true, writerElapsedMs: 0 });
    writerTimerRef.current = window.setInterval(() => {
      patchTurn(turnId, { writerElapsedMs: Date.now() - writerStartedAt });
    }, 250);
    let accumulated = '';
    try {
      for await (const event of recommendations.answerStream(activeSessionId, turnId, { signal: controller.signal })) {
        if (event.event === 'delta') {
          accumulated += String(event.data.text || '');
          patchTurn(turnId, { answer: accumulated });
        } else if (event.event === 'done') {
          stopWriterTimer();
          // done 带的是回填过链接的最终正文，覆盖流式累积的裸文本。
          patchTurn(turnId, {
            answer: String(event.data.markdown || accumulated),
            answerDone: true,
            streaming: false,
            failed: null,
            writerDurationMs: Math.max(0, Number(event.data.duration_ms) || 0),
            writerElapsedMs: 0,
          });
          return;
        } else if (event.event === 'error') {
          patchTurn(turnId, { failed: `生成回答失败：${String(event.data.message || '未知错误')}` });
        } else if (event.event === 'aborted') {
          stopWriterTimer();
          patchTurn(turnId, {
            aborted: true,
            answer: '',
            followUps: [],
            failed: null,
            answerDone: true,
            streaming: false,
            writerElapsedMs: 0,
          });
          return;
        }
      }
      stopWriterTimer();
      patchTurn(turnId, {
        answerDone: true,
        streaming: false,
        writerDurationMs: Date.now() - writerStartedAt,
        writerElapsedMs: 0,
      });
    } catch (streamError) {
      if (controller.signal.aborted) {
        stopWriterTimer();
        return;
      }
      stopWriterTimer();
      patchTurn(turnId, {
        streaming: false,
        failed: streamError instanceof Error ? streamError.message : '回答流中断',
        writerDurationMs: Date.now() - writerStartedAt,
        writerElapsedMs: 0,
      });
    }
  }, [patchTurn, stopWriterTimer]);

  const applyMessages = useCallback((turnId: string, messages: RecommendationMessage[]) => {
    const steps: RecommendationAgentSearchStep[] = [];
    let question: RecommendationAgentQuestion | null = null;
    let brief: RecommendationAgentBrief | null = null;
    let aborted = false;
    let understandingDurationMs: number | null = null;
    let deepEvalDurationMs: number | null = null;
    let briefDurationMs: number | null = null;

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
      const durationMs = Math.max(0, Number(payload.duration_ms) || 0);
      if (messageType === 'agent_understanding') {
        understandingDurationMs = durationMs;
      } else if (messageType === 'agent_step' && payload.step) {
        steps.push(payload.step as RecommendationAgentSearchStep);
      } else if (messageType === 'agent_question' && payload.question) {
        question = payload.question as RecommendationAgentQuestion;
      } else if (messageType === 'agent_brief' && payload.brief) {
        brief = payload.brief as RecommendationAgentBrief;
        briefDurationMs = durationMs;
      } else if (messageType === 'agent_deep_eval') {
        deepEvalDurationMs = durationMs;
      } else if (messageType === 'agent_aborted') {
        aborted = true;
      }
    }
    return {
      steps,
      question,
      brief,
      aborted,
      understandingDurationMs,
      deepEvalDurationMs,
      briefDurationMs,
    };
  }, []);

  /**
   * Follow one turn until the backend says it ended.
   *
   * Single-flight: the next poll is scheduled only after the previous one has
   * come back, so requests can never overlap however slow the API is.
   *
   * The page is deliberately **not** allowed to decide that a turn failed. It
   * used to, at tick 301 (~361s) — and a real production turn took 376.8s and
   * was killed by exactly that. Worse, the false failure offered a retry
   * button, so the user would start a second billed agent run next to the
   * first one that was still working. Only `progress.failed` ends a turn now.
   */
  const startPolling = useCallback((activeSessionId: string, turnId: string) => {
    stopPolling();
    const token = pollTokenRef.current;
    const startedAt = Date.now();
    let unreachableStreak = 0;
    elapsedTimerRef.current = window.setInterval(() => {
      patchTurn(turnId, { elapsedMs: Date.now() - startedAt });
    }, 1000);

    const tick = async () => {
      if (pollTokenRef.current !== token) return;
      patchTurn(turnId, { elapsedMs: Date.now() - startedAt });

      let progress: RecommendationAgentTurnProgress | null = null;
      try {
        progress = await recommendations.turnProgress(activeSessionId, turnId);
        unreachableStreak = 0;
        patchTurn(turnId, { unreachable: false });
      } catch {
        // 「暂时联系不上后端」和「后端说这一轮失败了」是两回事，这里是本批
        // 最核心的语义分界。网络问题只能提示，绝不标失败、绝不引导重试。
        unreachableStreak += 1;
        if (unreachableStreak >= POLL_UNREACHABLE_AFTER) {
          patchTurn(turnId, { unreachable: true });
        }
      }
      if (pollTokenRef.current !== token) return;

      if (progress) {
        const {
          steps,
          question,
          brief,
          understandingDurationMs,
          deepEvalDurationMs,
          briefDurationMs,
        } = applyMessages(turnId, progress.messages);
        patchTurn(turnId, {
          steps,
          understandingDurationMs,
          deepEvalDurationMs,
          briefDurationMs,
        });

        if (progress.aborted) {
          // 另一个页签把这一轮停了。
          stopPolling();
          patchTurn(turnId, { aborted: true, answerDone: true, streaming: false, unreachable: false });
          return;
        }
        if (progress.failed) {
          stopPolling();
          patchTurn(turnId, {
            failed: progress.error_message || '这一轮没能跑完。',
            answerDone: true,
            streaming: false,
            unreachable: false,
          });
          return;
        }
        if (question) {
          stopPolling();
          patchTurn(turnId, { question, answerDone: true, unreachable: false });
          return;
        }
        if (brief) {
          // 正文由 worker 写、由 answer-stream 订阅回放（第一批）。这里只是
          // 把流接上，接晚了也不丢字：订阅端会把已经写好的草稿一次补齐。
          stopPolling();
          patchTurn(turnId, {
            followUps: normalizeBriefFollowUps(brief.follow_up_suggestions),
            unreachable: false,
          });
          void streamAnswer(activeSessionId, turnId);
          return;
        }
        if (progress.job_status === 'succeeded' || progress.job_status === 'missing') {
          // 任务收尾了却什么都没留下。如实说，别一直轮询下去 —— 后端读任务
          // 状态在读消息之前，所以这里不会撞上「正文刚写完还没读到」那一瞬。
          stopPolling();
          patchTurn(turnId, {
            failed: '这一轮没有跑完。',
            answerDone: true,
            streaming: false,
            unreachable: false,
          });
          return;
        }
      }

      pollTimerRef.current = window.setTimeout(
        () => void tick(),
        pollDelayMs(Date.now() - startedAt),
      );
    };

    // 发起后立刻问一次，别让用户先盯着一个空壳等三秒。
    void tick();
  }, [applyMessages, patchTurn, stopPolling, streamAnswer]);

  const send = useCallback(async (
    message: string,
    attachmentIds: string[] = [],
    retryOfTurnId?: string,
  ) => {
    setError(null);
    try {
      const turn = await recommendations.agentTurn({
        mode: 'buyer_to_target',
        session_id: sessionId || undefined,
        user_message: message,
        attachment_ids: attachmentIds,
        retry_of_turn_id: retryOfTurnId,
        buyer_intent_id: anchorIntentId || undefined,
      });
      if (!sessionId) {
        setSessionId(turn.session_id);
        const next = new URLSearchParams(searchParams);
        next.set('session', turn.session_id);
        setSearchParams(next, { replace: true });
      }
      setAttachments([]);
      setTurns((prev) => {
        // 被重试的那一轮折叠成一行，但**不隐藏** —— 完全藏掉会让用户不知道
        // 自己发过，转头在别处重复发一遍。
        const marked = prev.map((item) =>
          retryOfTurnId && item.turnId === retryOfTurnId
            ? { ...item, supersededBy: turn.turn_id }
            : item,
        );
        const created: AgentTurnState = {
          turnId: turn.turn_id,
          userMessage: message,
          steps: [],
          question: null,
          followUps: [],
          answer: '',
          answerDone: false,
          streaming: false,
          failed: null,
          unreachable: false,
          aborted: false,
          retryOfTurnId: turn.retry_of_turn_id,
          supersededBy: null,
          elapsedMs: 0,
          understandingDurationMs: null,
          deepEvalDurationMs: null,
          briefDurationMs: null,
          writerDurationMs: null,
          writerElapsedMs: 0,
        };
        // 重试出现在它所替代的那一轮**原来的位置**，不是被冲到对话最底下。
        const at = retryOfTurnId ? marked.findIndex((item) => item.turnId === retryOfTurnId) : -1;
        if (at < 0) return [...marked, created];
        return [...marked.slice(0, at + 1), created, ...marked.slice(at + 1)];
      });
      startPolling(turn.session_id, turn.turn_id);
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : '发送失败');
    }
  }, [anchorIntentId, searchParams, sessionId, setSearchParams, startPolling]);

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
      stopWriterTimer();
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
  }, [activeTurn, patchTurn, sessionId, stopPolling, stopWriterTimer, stopping]);

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
    // 拿掉需求卡片就等于取消锚定，否则界面上看不见它却还在生效。
    if (key === REQUIREMENT_KEY) setAnchorIntentId(null);
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
    stopWriterTimer();
    streamAbortRef.current?.abort();
    setSessionId(null);
    setTurns([]);
    setError(null);
    setAttachments([]);
    setSearchParams(new URLSearchParams(), { replace: true });
  }, [setSearchParams, stopPolling, stopWriterTimer]);

  const restoreSession = useCallback(async (restoreId: string) => {
    let resumeTurnIds: string[] = [];
    let unresolvedTurnIds: string[] = [];
    try {
      const messages = await recommendations.messages(restoreId, { limit: 500 });
      const rebuilt = rebuildTurns(messages);
      resumeTurnIds = rebuilt.resumeTurnIds;
      unresolvedTurnIds = rebuilt.unresolvedTurnIds;
      setSessionId(restoreId);
      setTurns(rebuilt.turns);
    } catch {
      setError('恢复对话失败，可能已被删除');
      return;
    }

    // 什么终态都没有的轮次：问后端到底还在不在跑。仍在跑就接着轮询，
    // 别再像从前那样一律标成「这一轮没有跑完」—— 那是重开一个正常运行中的
    // 会话就会看到的假失败。
    let liveTurnId: string | null = null;
    for (const turnId of unresolvedTurnIds) {
      let progress;
      try {
        progress = await recommendations.turnProgress(restoreId, turnId);
      } catch {
        patchTurn(turnId, { unreachable: true });
        continue;
      }
      if (progress.aborted) {
        patchTurn(turnId, { aborted: true, answerDone: true });
      } else if (progress.failed) {
        patchTurn(turnId, { failed: progress.error_message || '这一轮没能跑完。', answerDone: true });
      } else if (progress.job_status === 'queued' || progress.job_status === 'retry_waiting'
                 || progress.job_status === 'running') {
        liveTurnId = turnId;
      } else {
        // 任务已经收尾却什么都没留下。说清楚，别装作还在跑。
        patchTurn(turnId, { failed: '这一轮没有跑完。', answerDone: true });
      }
    }
    // 只有一个轮询器，所以只跟最后那一轮 —— 那是用户正在等的那一轮。
    // 正常情况下也只可能有一轮在跑：输入框在忙的时候是锁住的。
    if (liveTurnId) startPolling(restoreId, liveTurnId);

    // 第一批之前，正文只在 SSE 的 done 事件里落库，所以关页签会留下「素材齐了、
    // 正文没写」的轮次。现在正文归 worker 写，补连一次拿到的是回放而不是重新
    // 生成；worker 还在写时则是接着往下流。
    for (const turnId of resumeTurnIds) {
      await streamAnswer(restoreId, turnId);
    }
  }, [patchTurn, startPolling, streamAnswer]);

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
        setAnchorIntentId(null);
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
      // 正文进输入框只是让人能改；锚点是给深评用的，两者都要。
      setAnchorIntentId(intentId);
    } catch {
      setAnchorIntentId(null);
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
    stopWriterTimer();
    streamAbortRef.current?.abort();
    setTurns([]);
    const next = new URLSearchParams();
    next.set('session', pickId);
    setSearchParams(next);
    void restoreSession(pickId);
  };

  const empty = turns.length === 0;
  const attemptNumbers = countRetryAttempts(turns);
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
            attempt={attemptNumbers.get(turn.turnId)}
            onSendSuggestion={(text) => void send(text)}
            onRetry={() => void send(turn.userMessage, [], turn.turnId)}
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
  /**
   * 什么终态都没有的轮次。**光看消息表分不出「还在跑」和「已经死了」** ——
   * 任务挂掉时一条消息都不会写。以前这里直接判「这一轮没有跑完」，于是重开
   * 一个后端仍在跑的会话就会看到一个假失败。交给调用方问后端。
   */
  unresolvedTurnIds: string[];
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
      unreachable: false,
      aborted: false,
      retryOfTurnId: null,
      supersededBy: null,
      elapsedMs: 0,
      understandingDurationMs: null,
      deepEvalDurationMs: null,
      briefDurationMs: null,
      writerDurationMs: null,
      writerElapsedMs: 0,
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
      if (turnId) {
        // 用户消息自己就带 turn_id，直接建轮：一轮如果还没写出任何过程消息
        // （刚入队、或正在跑第一次模型调用），也必须能被还原和继续轮询。
        const turn = ensure(turnId);
        turn.userMessage = message.content;
        turn.retryOfTurnId = String(metadata.retry_of_turn_id || '') || null;
      } else {
        pendingUserMessage = message.content;
      }
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
    const durationMs = Math.max(0, Number(payload.duration_ms) || 0);
    if (messageType === 'agent_understanding') {
      turn.understandingDurationMs = durationMs;
    } else if (messageType === 'agent_step' && payload.step) {
      turn.steps.push(payload.step as RecommendationAgentSearchStep);
    } else if (messageType === 'agent_question' && payload.question) {
      turn.question = payload.question as RecommendationAgentQuestion;
    } else if (messageType === 'agent_brief' && payload.brief) {
      turn.followUps = normalizeBriefFollowUps(
        (payload.brief as RecommendationAgentBrief).follow_up_suggestions,
      );
      turn.briefDurationMs = durationMs;
      landed.get(turnId)!.brief = true;
    } else if (messageType === 'agent_deep_eval') {
      turn.deepEvalDurationMs = durationMs;
    } else if (messageType === 'agent_answer') {
      turn.answer = String(payload.markdown || '');
      turn.writerDurationMs = durationMs;
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
  // 重试过的轮次折叠到新尝试底下 —— 折叠，不是隐藏。
  for (const turn of turns) {
    if (!turn.retryOfTurnId) continue;
    const original = byTurn.get(turn.retryOfTurnId);
    if (original) original.supersededBy = turn.turnId;
  }

  const resumeTurnIds: string[] = [];
  const unresolvedTurnIds: string[] = [];
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
    // 不在这里判失败：后端说了才算。
    turn.answerDone = false;
    unresolvedTurnIds.push(turn.turnId);
  }
  return { turns, resumeTurnIds, unresolvedTurnIds };
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
