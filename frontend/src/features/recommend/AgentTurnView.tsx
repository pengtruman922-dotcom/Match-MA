import { useState } from 'react';
import { AlertTriangle, Check, ChevronDown, ChevronRight, Copy, Loader2, WifiOff } from 'lucide-react';
import type { RecommendationAgentQuestion, RecommendationAgentSearchStep } from '../../types/api';
import AgentProcessLine from './AgentProcessLine';
import TinyMarkdown from './TinyMarkdown';

/** 超过这个时长只说「仍在处理」。判失败是后端的事，不是这个组件的。 */
const LONG_RUNNING_NOTICE_MS = 5 * 60_000;

export interface AgentTurnState {
  turnId: string;
  userMessage: string;
  steps: RecommendationAgentSearchStep[];
  question: RecommendationAgentQuestion | null;
  followUps: string[];
  answer: string;
  answerDone: boolean;
  streaming: boolean;
  /** 后端判定的失败原因。**只有后端能写这一项** —— 前端自判超时造成过假失败。 */
  failed: string | null;
  /** 连续拿不到进度。是「暂时联系不上」，不是「跑失败了」，所以不给重试按钮。 */
  unreachable: boolean;
  /** 用户点了停止。终态，不重试、不续接、不进下一轮上下文。 */
  aborted: boolean;
  /** 这一轮在重试哪一轮。 */
  retryOfTurnId: string | null;
  /** 这一轮已经被哪一轮重试了；有值就折叠成一行，但绝不完全隐藏。 */
  supersededBy: string | null;
  /** 进行中的前端墙钟；完成后展示值只取下面的落库耗时。 */
  elapsedMs: number;
  understandingDurationMs: number | null;
  deepEvalDurationMs: number | null;
  briefDurationMs: number | null;
  writerDurationMs: number | null;
  writerElapsedMs: number;
}

export default function AgentTurnView({
  turn,
  attempt,
  onSendSuggestion,
  onRetry,
}: {
  turn: AgentTurnState;
  /** 这是第几次尝试；只有被重试过的轮次需要显示。 */
  attempt?: number;
  onSendSuggestion: (text: string) => void;
  onRetry: () => void;
}) {
  const running = !turn.answerDone && !turn.failed && !turn.question && !turn.aborted;
  const longRunning = running && turn.elapsedMs >= LONG_RUNNING_NOTICE_MS;

  if (turn.supersededBy) {
    return <SupersededTurn turn={turn} attempt={attempt} />;
  }

  return (
    <div className="space-y-3" data-testid="agent-turn" data-turn-id={turn.turnId}>
      <div className="flex justify-end">
        <p className="max-w-[80%] whitespace-pre-wrap border-l-2 border-l-brand-500 bg-brand-50/60 px-3 py-2 text-sm text-gray-800">
          {turn.userMessage}
        </p>
      </div>

      <AgentProcessLine
        steps={turn.steps}
        running={running}
        elapsedMs={turn.elapsedMs}
        understandingDurationMs={turn.understandingDurationMs}
        deepEvalDurationMs={turn.deepEvalDurationMs}
        briefDurationMs={turn.briefDurationMs}
        writerDurationMs={turn.writerDurationMs}
        writerElapsedMs={turn.writerElapsedMs}
        writerRunning={turn.streaming}
      />

      {/*
        联系不上后端 ≠ 这一轮失败了。刻意不给重试按钮：假失败诱导用户重试、
        重试又并发开出第二个付费任务，正是这一批要切断的链条。
      */}
      {turn.unreachable && !turn.failed && !turn.aborted && (
        <p
          className="inline-flex items-center gap-1.5 text-xs text-gray-500"
          data-testid="agent-unreachable"
        >
          <WifiOff className="h-3 w-3" />
          暂时无法获取进度，正在重试连接…任务仍在后台运行。
        </p>
      )}

      {longRunning && !turn.unreachable && (
        <p className="text-xs text-gray-500" data-testid="agent-long-running">
          处理时间较长，任务仍在运行。可以继续等，也可以点停止。
        </p>
      )}

      {turn.question && <ClarifyBlock question={turn.question} onSubmit={onSendSuggestion} />}

      {turn.aborted && (
        <p className="text-sm text-gray-500" data-testid="agent-aborted">任务已停止。</p>
      )}

      {turn.failed && !turn.aborted && (
        <div className="flex items-start gap-2 border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <div className="space-y-1">
            <p>{turn.failed}</p>
            <button type="button" onClick={onRetry} className="text-brand-600 hover:underline">
              重试这一轮
            </button>
          </div>
        </div>
      )}

      {!turn.aborted && !turn.failed && !turn.question && (turn.answer || turn.streaming) && (
        <div className="space-y-2" data-testid="agent-answer">
          <TinyMarkdown text={turn.answer} />
          {turn.streaming && !turn.answer && (
            <p className="inline-flex items-center gap-1.5 text-xs text-gray-400">
              <Loader2 className="h-3 w-3 animate-spin" />
              正在整理推荐…
            </p>
          )}
          {turn.answerDone && <CopyButton text={turn.answer} />}
        </div>
      )}

      {turn.answerDone && Boolean(turn.answer.trim()) && !turn.aborted && !turn.failed && !turn.question
        && turn.followUps.length > 0 && (
        <div className="flex flex-wrap gap-1.5" data-testid="agent-follow-ups">
          {turn.followUps.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => onSendSuggestion(suggestion)}
              className="border border-gray-200 px-2.5 py-1 text-xs text-gray-600 hover:border-brand-500 hover:text-brand-600"
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * A turn the user retried: one grey line, expandable.
 *
 * Folded rather than hidden. A hidden attempt is one the user does not know
 * they made, and the next thing they do is send it again somewhere else.
 */
function SupersededTurn({ turn, attempt }: { turn: AgentTurnState; attempt?: number }) {
  const [open, setOpen] = useState(false);
  const label = attempt ? `第 ${attempt} 次尝试` : '上一次尝试';
  return (
    <div data-testid="agent-turn-superseded" data-turn-id={turn.turnId}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {label}{turn.failed ? '失败' : '未完成'}（{open ? '收起' : '查看详情'}）
      </button>
      {open && (
        <div className="mt-2 space-y-2 border-l border-gray-200 pl-3">
          <p className="whitespace-pre-wrap text-xs text-gray-500">{turn.userMessage}</p>
          {turn.failed && <p className="text-xs text-amber-700">{turn.failed}</p>}
          <AgentProcessLine
            steps={turn.steps}
            running={false}
            elapsedMs={turn.elapsedMs}
            understandingDurationMs={turn.understandingDurationMs}
            deepEvalDurationMs={turn.deepEvalDurationMs}
            briefDurationMs={turn.briefDurationMs}
            writerDurationMs={turn.writerDurationMs}
            writerElapsedMs={turn.writerElapsedMs}
            writerRunning={false}
          />
        </div>
      )}
    </div>
  );
}

/**
 * Answer the agent's questions, then submit once.
 *
 * Every option used to fire the next turn immediately, so with three questions
 * the consultant answered the first one and the other two were gone. The
 * backend has always supported up to three; this was purely the front end
 * sending too early.
 */
function ClarifyBlock({
  question,
  onSubmit,
}: {
  question: RecommendationAgentQuestion;
  onSubmit: (text: string) => void;
}) {
  const [picked, setPicked] = useState<Record<number, string>>({});
  const answered = question.questions
    .map((item, index) => ({ item, choice: picked[index] }))
    .filter((entry) => Boolean(entry.choice));

  const choose = (index: number, option: string) => {
    setPicked((prev) => (prev[index] === option
      // 再点一次就是取消选择：单选也得能反悔。
      ? Object.fromEntries(Object.entries(prev).filter(([key]) => key !== String(index)))
      : { ...prev, [index]: option }));
  };

  return (
    <div className="space-y-3 border border-gray-200 bg-white px-3 py-3 text-sm" data-testid="agent-question">
      {question.reason && <p className="text-gray-700">{question.reason}</p>}
      {question.questions.map((item, index) => (
        <div key={index} className="space-y-1.5">
          <p className="text-gray-800">{index + 1}. {item.question}</p>
          <div className="flex flex-wrap gap-1.5">
            {item.options.map((option) => {
              const selected = picked[index] === option;
              return (
                <button
                  key={option}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => choose(index, option)}
                  className={
                    selected
                      ? 'border border-brand-500 bg-brand-50 px-2.5 py-1 text-xs text-brand-700'
                      : 'border border-gray-200 px-2.5 py-1 text-xs text-gray-700 hover:border-brand-500 hover:bg-brand-50 hover:text-brand-600'
                  }
                >
                  {option}
                </button>
              );
            })}
          </div>
        </div>
      ))}
      <div className="flex items-center gap-3 pt-1">
        <button
          type="button"
          disabled={answered.length === 0}
          onClick={() => onSubmit(composeClarifyAnswer(question, picked))}
          data-testid="agent-question-submit"
          className={
            answered.length === 0
              ? 'cursor-not-allowed border border-gray-200 px-3 py-1 text-xs text-gray-300'
              : 'border border-brand-500 bg-brand-500 px-3 py-1 text-xs text-white hover:bg-brand-600'
          }
        >
          提交回答{answered.length > 0 ? `（${answered.length}/${question.questions.length}）` : ''}
        </button>
        <button
          type="button"
          onClick={() => onSubmit('跳过这些问题，先按现有条件给我结果')}
          className="text-xs text-gray-500 hover:text-brand-600 hover:underline"
        >
          跳过，先看结果
        </button>
      </div>
    </div>
  );
}

/**
 * Build the message the answers become.
 *
 * The question text has to ride along. Sending bare option values loses the
 * question entirely — and when the options are 「是」/「否」 the parser has
 * nothing at all to attach them to.
 */
function composeClarifyAnswer(
  question: RecommendationAgentQuestion,
  picked: Record<number, string>,
): string {
  return question.questions
    .map((item, index) => (picked[index] ? `${item.question}：${picked[index]}` : ''))
    .filter(Boolean)
    .join('；');
}

/** Copies the bare text — links are for the page, not for the client's WeChat. */
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(stripInternalLinks(text));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <button
      type="button"
      onClick={() => void copy()}
      className="inline-flex items-center gap-1 border border-gray-200 px-2.5 py-1 text-xs text-gray-600 hover:border-brand-500 hover:text-brand-600"
      data-testid="agent-copy"
    >
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {copied ? '已复制' : '复制'}
    </button>
  );
}

/** Mirror of the backend's `plain_text_for_copy`: links are page furniture. */
function stripInternalLinks(text: string): string {
  return text.replace(/\[([^\]]+)\]\((?:\/[^)]*)\)/g, '$1');
}
