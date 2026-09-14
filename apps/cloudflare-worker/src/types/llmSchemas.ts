// ponytail: TypeScript interfaces + minimal runtime guard (zod not installed; add if needed)
export interface EventAnalysisResult {
  entity_profile: string;
  context: string;
  impact: string;
  conviction_score: number;
}

export interface ChatReportResult {
  summary: string;
  risk_score: number;
  thesis: string;
  evidence: { fact: string; source: string }[];
  tool_calls: unknown[];
  disclaimer: string;
}

export interface ConsolidatedReport {
  analysis: EventAnalysisResult;
  data_summary: string;
  conviction_score: number;
  alert_recommendation: string;
}

export function guardEventAnalysis(obj: unknown): EventAnalysisResult {
  if (!obj || typeof obj !== "object") throw new Error("bad_event_analysis");
  const o = obj as Record<string, unknown>;
  return {
    entity_profile: String(o.entity_profile ?? ""),
    context: String(o.context ?? ""),
    impact: String(o.impact ?? ""),
    conviction_score: Math.max(0, Math.min(100, Number(o.conviction_score ?? 0))),
  };
}
