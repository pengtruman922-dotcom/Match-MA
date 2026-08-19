import type { AgentTurnState } from './AgentTurnView';

/**
 * 轮询节奏：单飞 + 三段，越等越慢。
 *
 * 原来是 1.2 秒一次、上限 300 次，一轮最多约 600 个 HTTP 请求，而且
 * `setInterval(async …)` 没有单飞保护，单次请求超过 1.2 秒就开始重叠。
 *
 * 前 30 秒的密段是刻意加的：一轮总耗时中位数才 105 秒，澄清框和进度步骤
 * 如果统一等 10 秒，感知上是明显回退。密段只多 8 次请求。
 */
export const POLL_FAST_INTERVAL_MS = 3_000;
export const POLL_FAST_WINDOW_MS = 30_000;
export const POLL_MEDIUM_INTERVAL_MS = 10_000;
export const POLL_MEDIUM_WINDOW_MS = 5 * 60_000;
export const POLL_SLOW_INTERVAL_MS = 30_000;
/** 连续这么多次拿不到进度才提示「暂时无法获取」，避开一次抖动就报警。 */
export const POLL_UNREACHABLE_AFTER = 3;

/** 已经等了多久 → 下一次隔多久再问。 */
export function pollDelayMs(elapsedMs: number): number {
  if (elapsedMs < POLL_FAST_WINDOW_MS) return POLL_FAST_INTERVAL_MS;
  if (elapsedMs < POLL_MEDIUM_WINDOW_MS) return POLL_MEDIUM_INTERVAL_MS;
  return POLL_SLOW_INTERVAL_MS;
}

/**
 * Number each turn inside its retry chain, so a folded attempt can say which
 * one it was. A turn nobody retried is not part of a chain and gets no number.
 */
export function countRetryAttempts(turns: AgentTurnState[]): Map<string, number> {
  const attempts = new Map<string, number>();
  const byId = new Map(turns.map((turn) => [turn.turnId, turn]));
  for (const turn of turns) {
    if (!turn.retryOfTurnId && !turn.supersededBy) continue;
    let depth = 1;
    let cursor: string | null = turn.retryOfTurnId;
    // seen 不是洁癖：retry_of_turn_id 来自服务端数据，成环就会在这里死循环。
    const seen = new Set<string>([turn.turnId]);
    while (cursor && byId.has(cursor) && !seen.has(cursor)) {
      seen.add(cursor);
      depth += 1;
      cursor = byId.get(cursor)!.retryOfTurnId;
    }
    attempts.set(turn.turnId, depth);
  }
  return attempts;
}
