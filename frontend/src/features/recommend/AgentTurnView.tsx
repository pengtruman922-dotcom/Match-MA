import { useState } from 'react';
import { AlertTriangle, Check, Copy, Loader2 } from 'lucide-react';
import type { RecommendationAgentQuestion, RecommendationAgentSearchStep } from '../../types/api';
import AgentProcessLine from './AgentProcessLine';
import TinyMarkdown from './TinyMarkdown';

export interface AgentTurnState {
  turnId: string;
  userMessage: string;
  steps: RecommendationAgentSearchStep[];
  question: RecommendationAgentQuestion | null;
  followUps: string[];
  answer: string;
  answerDone: boolean;
  streaming: boolean;
  failed: string | null;
  elapsedSeconds: number;
}

export default function AgentTurnView({
  turn,
  onSendSuggestion,
  onRetry,
}: {
  turn: AgentTurnState;
  onSendSuggestion: (text: string) => void;
  onRetry: () => void;
}) {
  const running = !turn.answerDone && !turn.failed && !turn.question;

  return (
    <div className="space-y-3" data-testid="agent-turn" data-turn-id={turn.turnId}>
      <div className="flex justify-end">
        <p className="max-w-[80%] whitespace-pre-wrap border-l-2 border-l-brand-500 bg-brand-50/60 px-3 py-2 text-sm text-gray-800">
          {turn.userMessage}
        </p>
      </div>

      <AgentProcessLine
        steps={turn.steps}
        running={running && !turn.streaming}
        elapsedSeconds={turn.elapsedSeconds}
      />

      {turn.question && <ClarifyBlock question={turn.question} onPick={onSendSuggestion} />}

      {turn.failed && (
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

      {(turn.answer || turn.streaming) && (
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

      {turn.answerDone && turn.followUps.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
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

function ClarifyBlock({
  question,
  onPick,
}: {
  question: RecommendationAgentQuestion;
  onPick: (text: string) => void;
}) {
  return (
    <div className="space-y-3 border border-gray-200 bg-white px-3 py-3 text-sm" data-testid="agent-question">
      {question.reason && <p className="text-gray-700">{question.reason}</p>}
      {question.questions.map((item, index) => (
        <div key={index} className="space-y-1.5">
          <p className="text-gray-800">{index + 1}. {item.question}</p>
          <div className="flex flex-wrap gap-1.5">
            {item.options.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => onPick(option)}
                className="border border-gray-200 px-2.5 py-1 text-xs text-gray-700 hover:border-brand-500 hover:bg-brand-50 hover:text-brand-600"
              >
                {option}
              </button>
            ))}
          </div>
        </div>
      ))}
      <button
        type="button"
        onClick={() => onPick('跳过这些问题，先按现有条件给我结果')}
        className="text-xs text-gray-500 hover:text-brand-600 hover:underline"
      >
        跳过，先看结果
      </button>
    </div>
  );
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
