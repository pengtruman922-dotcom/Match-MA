import type {
  RecommendationCandidate,
  RecommendationFunnel,
  RecommendationScenarioRef,
  RecommendationMessage,
  RecommendationSelectedItem,
  RecommendationSessionBundle,
} from '../../types/api';

export interface CandidateView {
  pairKey: string;
  mode: 'buyer_to_target' | 'target_to_buyer';
  sellerTargetId: string | null;
  buyerIntentId: string | null;
  buyerPartyId: string | null;
  name: string;
  detailPath: string | null;
  strength: string;
  score: number;
  matchSummary: string;
  gapSummary: string;
  riskSummary: string | null;
  evidence: Record<string, unknown>;
  matchState: string | null;
  missingDimensions: string[];
  bestScenarioLabel: string | null;
  matchedScenarioLabels: string[];
  deepEvalGrade: string | null;
  deepEvalReason: string | null;
  deepEvalRisks: string | null;
  relationId: string | null;
  relationStatus: string | null;
  deepProgressElsewhere: boolean;
  selected: boolean;
  selectedItemId: string | null;
}

export type DeepEvalState = 'none' | 'running' | 'done' | 'failed';

export interface Round {
  id: string;
  candidates: CandidateView[];
  deepEval: DeepEvalState;
  funnel: RecommendationFunnel | null;
  scenarios: RecommendationScenarioRef[];
}

export type TimelineEntry =
  | { kind: 'system'; id: string; text: string }
  | { kind: 'user'; id: string; text: string }
  | { kind: 'round'; id: string; round: Round }
  | { kind: 'report'; id: string; reportId: string | null; markdown: string };

export function candidatePairKey(sellerTargetId: string | null, buyerIntentId: string | null): string {
  return `${sellerTargetId || ''}:${buyerIntentId || ''}`;
}

const LEVEL_LABELS: Record<RecommendationCandidate['recommendation_level'], string> = {
  strong: '强推荐',
  recommended: '推荐',
  possible: '可关注',
  weak: '弱匹配',
};

export function levelToApi(label: string): RecommendationCandidate['recommendation_level'] {
  if (label.includes('强推荐')) return 'strong';
  if (label.includes('可关注')) return 'possible';
  if (label.includes('弱匹配')) return 'weak';
  return 'recommended';
}

export function mapCandidate(candidate: RecommendationCandidate): CandidateView {
  const isBuyerMode = candidate.mode === 'buyer_to_target';
  const targetName = candidate.seller_target_name || '未命名标的';
  const intentName = candidate.buyer_intent_name || '未命名意向';
  return {
    pairKey: candidatePairKey(candidate.seller_target_id, candidate.buyer_intent_id),
    mode: candidate.mode,
    sellerTargetId: candidate.seller_target_id,
    buyerIntentId: candidate.buyer_intent_id,
    buyerPartyId: candidate.buyer_party_id,
    name: isBuyerMode ? targetName : `${candidate.buyer_name || '未绑定买家'} / ${intentName}`,
    detailPath: isBuyerMode
      ? candidate.seller_target_id ? `/targets/${candidate.seller_target_id}` : null
      : candidate.buyer_intent_id ? `/buyer-intents/${candidate.buyer_intent_id}` : null,
    strength: `${LEVEL_LABELS[candidate.recommendation_level]} ${Math.round(candidate.score)}`,
    score: candidate.score,
    matchSummary: candidate.match_summary,
    gapSummary: candidate.gap_summary || '',
    riskSummary: candidate.risk_summary,
    evidence: candidate.evidence_json,
    matchState: candidate.match_state || null,
    missingDimensions: candidate.missing_dimensions || [],
    bestScenarioLabel: candidate.best_scenario_label || null,
    matchedScenarioLabels: candidate.matched_scenario_labels || [],
    deepEvalGrade: candidate.deep_eval?.grade || null,
    deepEvalReason: candidate.deep_eval?.reason || null,
    deepEvalRisks: candidate.deep_eval?.risks || null,
    relationId: candidate.relation_id || null,
    relationStatus: candidate.relation_status || null,
    deepProgressElsewhere: candidate.deep_progress_elsewhere || false,
    selected: false,
    selectedItemId: null,
  };
}

function activeSelectionByPair(selectedItems: RecommendationSelectedItem[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const item of selectedItems) {
    if (item.canceled_at) continue;
    map.set(candidatePairKey(item.seller_target_id, item.buyer_intent_id), item.id);
  }
  return map;
}

export function applySelection(candidates: CandidateView[], selectedItems: RecommendationSelectedItem[]): CandidateView[] {
  const byPair = activeSelectionByPair(selectedItems);
  return candidates.map((candidate) => {
    const selectedItemId = byPair.get(candidate.pairKey) || null;
    return { ...candidate, selected: Boolean(selectedItemId), selectedItemId };
  });
}

function parseJsonContent(message: RecommendationMessage): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(message.content) as unknown;
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function messageType(message: RecommendationMessage, content: Record<string, unknown> | null): string {
  return String(message.metadata_json?.message_type || content?.message_type || '');
}

/** Rebuild the chat timeline from persisted session messages. */
export function buildTimeline(bundle: RecommendationSessionBundle): TimelineEntry[] {
  const entries: TimelineEntry[] = [];
  const selectedItems = bundle.selected_items || [];
  // Candidate messages are an immutable historical snapshot.  Relation state
  // is intentionally recomputed by the server every time the bundle is read:
  // someone can start progress after this message was written.  Overlay the
  // current annotation before rendering so a successful “开始推进” never flips
  // back to “开始推进” on the next polling refresh.
  const annotatedInitial = candidatesByPair(bundle.initial_candidates || []);
  const annotatedReranked = candidatesByPair(bundle.reranked_candidates || []);

  for (const message of bundle.messages || []) {
    if (message.role === 'user' && message.content_type === 'text') {
      entries.push({ kind: 'user', id: message.id, text: message.content });
      continue;
    }
    if (message.role === 'assistant' && message.content_type === 'text') {
      entries.push({ kind: 'system', id: message.id, text: message.content });
      continue;
    }
    if (message.content_type === 'json') {
      const content = parseJsonContent(message);
      const type = messageType(message, content);
      const rawCandidates = Array.isArray(content?.candidates) ? (content?.candidates as RecommendationCandidate[]) : null;
      if (!rawCandidates) continue;
      const annotations = type === 'reranked_candidates' ? annotatedReranked : annotatedInitial;
      const candidates = applySelection(
        rawCandidates.map((candidate) => mapCandidate(annotations.get(candidatePairKey(
          candidate.seller_target_id,
          candidate.buyer_intent_id,
        )) || candidate)),
        selectedItems,
      );
      if (type === 'reranked_candidates') {
        const lastRound = [...entries].reverse().find((entry) => entry.kind === 'round');
        if (lastRound && lastRound.kind === 'round') {
          lastRound.round = { ...lastRound.round, candidates, deepEval: 'done' };
        }
      } else if (type === 'initial_candidates') {
        const funnel = (content?.funnel as RecommendationFunnel | undefined) || null;
        const scenarios = (content?.scenarios as RecommendationScenarioRef[] | undefined) || [];
        entries.push({
          kind: 'round',
          id: message.id,
          round: { id: message.id, candidates, deepEval: 'none', funnel, scenarios },
        });
      }
      continue;
    }
    if (message.content_type === 'markdown' && messageType(message, null) === 'recommendation_report') {
      entries.push({
        kind: 'report',
        id: message.id,
        reportId: (message.metadata_json?.report_id as string) || null,
        markdown: message.content,
      });
    }
  }

  const rerankStatus = bundle.rerank_status?.status;
  const lastRound = [...entries].reverse().find((entry) => entry.kind === 'round');
  if (lastRound && lastRound.kind === 'round' && lastRound.round.deepEval !== 'done') {
    if (rerankStatus === 'queued' || rerankStatus === 'running' || rerankStatus === 'retry_waiting') {
      lastRound.round = { ...lastRound.round, deepEval: 'running' };
    } else if (rerankStatus === 'failed') {
      lastRound.round = { ...lastRound.round, deepEval: 'failed' };
    }
  }
  return entries;
}

function candidatesByPair(candidates: RecommendationCandidate[]): Map<string, RecommendationCandidate> {
  return new Map(candidates.map((candidate) => [
    candidatePairKey(candidate.seller_target_id, candidate.buyer_intent_id),
    candidate,
  ]));
}

export function latestRoundEntry(entries: TimelineEntry[]): Extract<TimelineEntry, { kind: 'round' }> | null {
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    const entry = entries[index];
    if (entry.kind === 'round') return entry;
  }
  return null;
}
