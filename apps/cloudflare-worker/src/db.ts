import type { D1Database } from "@cloudflare/workers-types";
import type { CandidateEvent, CuratedWallet } from "./types";

function parseRow(row: Record<string, unknown> | null): CandidateEvent | null {
  if (!row) return null;
  let raw_json: Record<string, unknown> = {};
  if (typeof row.raw_json === "string") {
    try {
      raw_json = JSON.parse(row.raw_json);
    } catch {
      raw_json = {};
    }
  } else if (row.raw_json && typeof row.raw_json === "object") {
    raw_json = row.raw_json as Record<string, unknown>;
  }
  return {
    id: Number(row.id),
    wallet_id: row.wallet_id === null ? null : Number(row.wallet_id),
    chain: String(row.chain),
    tx_hash: String(row.tx_hash),
    log_index: Number(row.log_index),
    block_number: Number(row.block_number),
    event_type: String(row.event_type),
    raw_json,
    score: Number(row.score),
    dedupe_key: String(row.dedupe_key),
    status: String(row.status) as CandidateEvent["status"],
    attempt_count: Number(row.attempt_count),
    published_at: row.published_at === null ? null : Number(row.published_at),
    campaign_id: row.campaign_id === null ? null : Number(row.campaign_id),
    created_at: Number(row.created_at),
    updated_at: Number(row.updated_at),
  };
}

export async function claimNextPending(db: D1Database): Promise<CandidateEvent | null> {
  const info = await db
    .prepare(
      `UPDATE candidate_events
       SET status = 'processing', updated_at = strftime('%s','now')
       WHERE id = (
         SELECT id FROM candidate_events
         WHERE status = 'pending'
         ORDER BY created_at ASC, id ASC
         LIMIT 1
       )
       RETURNING *`,
    )
    .all();
  const rows = (info.results as Record<string, unknown>[]) || [];
  return parseRow(rows[0] || null);
}

export async function setStatus(
  db: D1Database,
  id: number,
  status: string,
  attemptCount?: number,
): Promise<void> {
  if (attemptCount !== undefined) {
    await db
      .prepare(
        `UPDATE candidate_events SET status = ?, attempt_count = ?, updated_at = strftime('%s','now') WHERE id = ?`,
      )
      .bind(status, attemptCount, id)
      .run();
  } else {
    await db
      .prepare(
        `UPDATE candidate_events SET status = ?, updated_at = strftime('%s','now') WHERE id = ?`,
      )
      .bind(status, id)
      .run();
  }
}

export async function recordFailure(
  db: D1Database,
  id: number,
  maxAttempts: number,
): Promise<string> {
  const info = await db
    .prepare(
      `UPDATE candidate_events
       SET attempt_count = attempt_count + 1,
           status = CASE WHEN (attempt_count + 1) >= ? THEN 'dead_letter' ELSE 'pending' END,
           updated_at = strftime('%s','now')
       WHERE id = ?
       RETURNING status`,
    )
    .bind(maxAttempts, id)
    .all();
  const rows = (info.results as Record<string, unknown>[]) || [];
  return String(rows[0]?.status || "pending");
}

export async function markPublished(db: D1Database, id: number): Promise<void> {
  await db
    .prepare(
      `UPDATE candidate_events SET status='completed', published_at=strftime('%s','now'), updated_at=strftime('%s','now') WHERE id = ?`,
    )
    .bind(id)
    .run();
}

export async function getCuratedActive(db: D1Database): Promise<CuratedWallet[]> {
  const info = await db
    .prepare(`SELECT * FROM curated_wallets WHERE is_active = 1`)
    .all();
  const rows = (info.results as Record<string, unknown>[]) || [];
  return rows.map((r) => ({
    id: Number(r.id),
    address: String(r.address).toLowerCase(),
    chain: String(r.chain),
    label: String(r.label),
    tags: (() => {
      try {
        return JSON.parse(String(r.tags || "[]"));
      } catch {
        return [];
      }
    })(),
    is_active: Number(r.is_active) === 1,
  }));
}

export async function insertPending(
  db: D1Database,
  data: {
    wallet_id: number;
    chain: string;
    tx_hash: string;
    log_index: number;
    block_number: number;
    event_type: string;
    value_usd: number;
    raw_json: Record<string, unknown>;
    dedupe_key: string;
    score: number;
  },
): Promise<void> {
  await db
    .prepare(
      `INSERT OR IGNORE INTO candidate_events
       (wallet_id, chain, tx_hash, log_index, block_number, event_type, raw_json, score, dedupe_key, status)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')`,
    )
    .bind(
      data.wallet_id,
      data.chain,
      data.tx_hash,
      data.log_index,
      data.block_number,
      data.event_type,
      JSON.stringify(data.raw_json),
      data.score,
      data.dedupe_key,
    )
    .run();
}

export async function countPublishedSince(
  db: D1Database,
  sinceSeconds: number,
): Promise<number> {
  const info = await db
    .prepare(
      `SELECT COUNT(*) as c FROM candidate_events WHERE published_at >= ?`,
    )
    .bind(sinceSeconds)
    .all();
  const rows = (info.results as Record<string, unknown>[]) || [];
  return Number(rows[0]?.c || 0);
}

export async function recentCountForWallet(
  db: D1Database,
  walletId: number,
  sinceSeconds: number,
): Promise<number> {
  const info = await db
    .prepare(
      `SELECT COUNT(*) as c FROM candidate_events WHERE wallet_id = ? AND created_at >= ?`,
    )
    .bind(walletId, sinceSeconds)
    .all();
  const rows = (info.results as Record<string, unknown>[]) || [];
  return Number(rows[0]?.c || 0);
}

export async function listRecentPublished(
  db: D1Database,
  sinceSeconds: number,
  limit = 20,
): Promise<CandidateEvent[]> {
  const info = await db
    .prepare(
      `SELECT * FROM candidate_events WHERE status='completed' AND published_at >= ? ORDER BY published_at DESC LIMIT ?`,
    )
    .bind(sinceSeconds, limit)
    .all();
  const rows = (info.results as Record<string, unknown>[]) || [];
  return rows.map((r) => parseRow(r)!).filter(Boolean);
}

export async function createAgentRun(
  db: D1Database,
  data: {
    trigger_type: string;
    trigger_ref_id: number;
    graph_name: string;
    status: string;
    input_json: unknown;
    output_json: unknown;
    latency_ms: number;
  },
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO agent_runs (trigger_type, trigger_ref_id, graph_name, status, input_json, output_json, latency_ms)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
    )
    .bind(
      data.trigger_type,
      data.trigger_ref_id,
      data.graph_name,
      data.status,
      JSON.stringify(data.input_json),
      JSON.stringify(data.output_json),
      data.latency_ms,
    )
    .run();
}

export async function createAuditLog(
  db: D1Database,
  data: {
    admin_id: number;
    action: string;
    target_type: string;
    target_id: string;
    diff_json: unknown;
  },
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO admin_audit_logs (admin_id, action, target_type, target_id, diff_json)
       VALUES (?, ?, ?, ?, ?)`,
    )
    .bind(
      data.admin_id,
      data.action,
      data.target_type,
      data.target_id,
      JSON.stringify(data.diff_json),
    )
    .run();
}

export async function purgeStale(db: D1Database, olderThanSeconds: number): Promise<number> {
  const info = await db
    .prepare(
      `DELETE FROM candidate_events WHERE status IN ('skipped','completed') AND created_at < ?`,
    )
    .bind(olderThanSeconds)
    .run();
  return Number((info.meta as { changes?: number }).changes || 0);
}

export { parseRow };
