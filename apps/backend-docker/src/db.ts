import { DatabaseSync } from "node:sqlite";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

export interface StoredEvent extends Record<string, unknown> {
  idempotency_key: string;
  chain: string;
  tx_hash: string;
  log_index: number;
  from_address: string;
  to_address: string;
  asset_symbol: string;
  token_address: string | null;
  amount: string;
  usd_value: number;
  action_type: string;
  wallet_address: string;
  wallet_label: string;
  wallet_category: string;
  price_usd: number;
  liquidity_usd: number | null;
  volume_24h: number | null;
  fdv: number | null;
  narrative: string | null;
  received_at: number;
}

const SCHEMA = `
CREATE TABLE IF NOT EXISTS events (
  idempotency_key TEXT PRIMARY KEY,
  chain TEXT NOT NULL,
  tx_hash TEXT NOT NULL,
  log_index INTEGER NOT NULL,
  from_address TEXT NOT NULL,
  to_address TEXT NOT NULL,
  asset_symbol TEXT NOT NULL,
  token_address TEXT,
  amount TEXT NOT NULL,
  usd_value REAL NOT NULL,
  action_type TEXT NOT NULL,
  wallet_address TEXT NOT NULL,
  wallet_label TEXT NOT NULL,
  wallet_category TEXT NOT NULL,
  price_usd REAL,
  liquidity_usd REAL,
  volume_24h REAL,
  fdv REAL,
  narrative TEXT,
  received_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_time ON events(received_at);
CREATE INDEX IF NOT EXISTS idx_events_narrative_time ON events(narrative, received_at);
CREATE INDEX IF NOT EXISTS idx_events_funder_time ON events(chain, from_address, received_at);
`;

let db: DatabaseSync | null = null;
let dbPath = "";

export function initDb(path: string): DatabaseSync {
  if (db && dbPath === path) return db;
  if (path !== ":memory:") mkdirSync(dirname(path), { recursive: true });
  db = new DatabaseSync(path);
  db.exec("PRAGMA journal_mode = WAL;");
  db.exec(SCHEMA);
  dbPath = path;
  return db;
}

export function getDb(): DatabaseSync {
  if (!db) throw new Error("database not initialized");
  return db;
}

export function closeDb(): void {
  db?.close();
  db = null;
  dbPath = "";
}

export function insertEvent(e: StoredEvent): boolean {
  const d = getDb();
  const r = d.prepare(
    `INSERT OR IGNORE INTO events (
      idempotency_key, chain, tx_hash, log_index, from_address, to_address,
      asset_symbol, token_address, amount, usd_value, action_type,
      wallet_address, wallet_label, wallet_category,
      price_usd, liquidity_usd, volume_24h, fdv, narrative, received_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
  ).run(
    e.idempotency_key, e.chain, e.tx_hash, e.log_index,
    (e.from_address || "").toLowerCase(), (e.to_address || "").toLowerCase(),
    e.asset_symbol, e.token_address, e.amount, e.usd_value, e.action_type,
    (e.wallet_address || "").toLowerCase(), e.wallet_label, e.wallet_category,
    e.price_usd, e.liquidity_usd, e.volume_24h, e.fdv, e.narrative, e.received_at,
  );
  return r.changes > 0;
}

export function eventExists(idempotencyKey: string): boolean {
  return getDb().prepare("SELECT 1 FROM events WHERE idempotency_key = ?").get(idempotencyKey) !== undefined;
}

export function eventsSince(sinceMs: number, untilMs: number): StoredEvent[] {
  return getDb().prepare(
    "SELECT * FROM events WHERE received_at >= ? AND received_at <= ? ORDER BY usd_value DESC",
  ).all(sinceMs, untilMs) as unknown as StoredEvent[];
}

export function countEvents(): number { return (getDb().prepare("SELECT COUNT(*) AS c FROM events").get() as { c: number }).c; }

/** Narrative volume: last 24h vs previous 24h. */
export function narrativeVelocity(nowMs: number): Array<{ narrative: string; volume24h: number; volumePrev24h: number; velocityPct: number }> {
  const rows = getDb().prepare(
    `SELECT narrative, SUM(CASE WHEN received_at >= ? THEN usd_value ELSE 0 END) AS v24,
            SUM(CASE WHEN received_at < ? THEN usd_value ELSE 0 END) AS vprev
     FROM events
     WHERE narrative IS NOT NULL AND received_at >= ? AND received_at < ?
     GROUP BY narrative`,
  ).all(
    nowMs - 24 * 3600_000,
    nowMs - 24 * 3600_000,
    nowMs - 48 * 3600_000,
    nowMs,
  ) as Array<{ narrative: string; v24: number | null; vprev: number | null }>;
  return rows.map((r) => {
    const v24 = Number(r.v24) || 0;
    const vPrev = Number(r.vprev) || 0;
    return {
      narrative: r.narrative,
      volume24h: v24,
      volumePrev24h: vPrev,
      velocityPct: vPrev > 0 ? Number((((v24 - vPrev) / vPrev) * 100).toFixed(1)) : v24 > 0 ? 100 : 0,
    };
  }).sort((a, b) => b.volume24h - a.volume24h);
}

/** Sub-50k transfers from one funder within the 6h rolling window (stealth). */
export function stealthSiblings(chain: string, fromAddress: string, sinceMs: number, excludeKey: string): number {
  const row = getDb().prepare(
    `SELECT COUNT(*) AS c FROM events
     WHERE chain = ? AND from_address = ? AND received_at >= ? AND idempotency_key != ?
       AND usd_value > 0 AND usd_value < 50000`,
  ).get(chain, fromAddress.toLowerCase(), sinceMs, excludeKey) as { c: number };
  return row.c;
}
