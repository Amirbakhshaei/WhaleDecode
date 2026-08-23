import type { D1Database } from "@cloudflare/workers-types";
import type { AlchemyEvent, CandidateInsert } from "./normalizer";
import { normalizeAlchemyEvent } from "./normalizer";
import type { PriceOracle } from "./priceOracle";
import { sentinelScore } from "./sentinel";
import { shouldInvestigate, passesChannelFloor } from "./eventGate";
import { investigateEvent } from "./llm";
import { TelegramClient } from "./telegram";
import { buildAlertText } from "./format";
import type { AppConfig } from "./config";
import type { CuratedWallet, InvestigationResult } from "./types";
import * as repo from "./db";

const MAX_ATTEMPTS = 3;

/** Ingest one Alchemy webhook event for a matched curated wallet. */
export async function ingestEvent(
  db: D1Database,
  event: AlchemyEvent,
  wallet: CuratedWallet,
  oracle: PriceOracle,
): Promise<boolean> {
  const insert: CandidateInsert | null = await normalizeAlchemyEvent(
    event,
    wallet.id,
    oracle,
  );
  if (!insert) return false;

  const now = Math.floor(Date.now() / 1000);
  const recent = await repo.recentCountForWallet(db, wallet.id, now - 300);
  insert.score = sentinelScore({
    event_type: insert.event_type,
    value_usd: insert.value_usd,
    wallet_id: wallet.id,
    curated_wallet_ids: new Set([wallet.id]),
    recent_count: recent,
  });
  await repo.insertPending(db, insert);
  return true;
}

/** Process one pending candidate. Returns false when the queue is empty. */
export async function processPending(
  db: D1Database,
  cfg: AppConfig,
): Promise<boolean> {
  const event = await repo.claimNextPending(db);
  if (!event) return false;

  const raw = event.raw_json;
  const valueUsd = Number(raw.value_usd || 0);

  try {
    // Pre-LLM whale gate (uses real USD value priced at ingestion).
    if (!shouldInvestigate({ score: event.score, valueUsd })) {
      await repo.setStatus(db, event.id, "skipped");
      return true;
    }

    const result: InvestigationResult = await investigateEvent(
      {
        id: event.id,
        chain: event.chain,
        tx_hash: event.tx_hash,
        event_type: event.event_type,
        raw_json: raw,
      },
      cfg,
    );

    // Channel floor after investigation.
    if (!passesChannelFloor(result.risk_score, valueUsd)) {
      await repo.setStatus(db, event.id, "skipped");
      await repo.createAgentRun(db, {
        trigger_type: "event",
        trigger_ref_id: event.id,
        graph_name: "event_investigation",
        status: "skipped",
        input_json: raw,
        output_json: result,
        latency_ms: result.latency_ms || 0,
      });
      return true;
    }

    if (!cfg.channelPublishEnabled || !cfg.channelChatId) {
      await repo.setStatus(db, event.id, "completed");
      return true;
    }

    const text = buildAlertText(
      {
        chain: event.chain,
        tx_hash: event.tx_hash,
        event_type: event.event_type,
        raw_json: raw,
      },
      result as unknown as Record<string, unknown>,
      cfg.botUsername,
    );

    const tg = new TelegramClient(cfg);
    try {
      await tg.sendMessage(cfg.channelChatId, text);
    } catch (e) {
      // Telegram unreachable: return to pending for retry on next drain.
      await repo.setStatus(db, event.id, "pending");
      throw e;
    }

    await repo.markPublished(db, event.id);
    await repo.createAgentRun(db, {
      trigger_type: "event",
      trigger_ref_id: event.id,
      graph_name: "event_investigation",
      status: "completed",
      input_json: raw,
      output_json: result,
      latency_ms: result.latency_ms || 0,
    });
    return true;
  } catch (e) {
    const next = await repo.recordFailure(db, event.id, MAX_ATTEMPTS);
    if (next === "dead_letter") {
      await repo.createAuditLog(db, {
        admin_id: 0,
        action: "candidate_event_dead_lettered",
        target_type: "candidate_event",
        target_id: String(event.id),
        diff_json: { dedupe_key: event.dedupe_key, error: String(e) },
      });
    }
    // Stop draining this invocation so we don't hammer the LLM on a hard failure.
    return false;
  }
}

/** Drain up to `limit` pending candidates. */
export async function drain(
  db: D1Database,
  cfg: AppConfig,
  limit = 10,
): Promise<number> {
  let processed = 0;
  for (let i = 0; i < limit; i++) {
    const ok = await processPending(db, cfg);
    if (!ok) break;
    processed++;
  }
  return processed;
}
