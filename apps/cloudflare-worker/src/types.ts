// Shared types for the Worker pipeline.

export type EventStatus =
  | "pending"
  | "processing"
  | "skipped"
  | "completed"
  | "dead_letter";

export interface RawLog {
  address?: string;
  topics?: string[];
  data?: string;
  blockNumber?: number | string;
  transactionHash?: string;
  logIndex?: number | string;
  [key: string]: unknown;
}

export interface CandidateEvent {
  id: number;
  wallet_id: number | null;
  chain: string;
  tx_hash: string;
  log_index: number;
  block_number: number;
  event_type: string;
  raw_json: Record<string, unknown>;
  score: number;
  dedupe_key: string;
  status: EventStatus;
  attempt_count: number;
  published_at: number | null;
  campaign_id: number | null;
  created_at: number;
  updated_at: number;
}

export interface InvestigationResult {
  summary: string;
  fundamental_summary: string;
  technical_summary: string;
  bias_summary: string;
  risk_score: number; // 0..1
  is_safe: boolean;
  thesis: string;
  entity_profile?: string;
  event_category?: string;
  from_label?: string;
  to_label?: string;
  asset?: string;
  total_value_usd?: number;
  latency_ms?: number;
}

export interface CuratedWallet {
  id: number;
  address: string;
  chain: string;
  label: string;
  tags: string[];
  is_active: boolean;
}
