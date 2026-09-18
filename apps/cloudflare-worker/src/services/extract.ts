import type { WhaleActivity } from "../types";

type Payload = Record<string, unknown> | null;

export function extractActivities(payload: unknown): WhaleActivity[] {
  if (Array.isArray(payload)) return payload as WhaleActivity[];
  if (!payload || typeof payload !== "object") return [];
  const p = payload as Record<string, unknown>;
  const event = p.event as Record<string, unknown> | undefined;
  if (Array.isArray(p.activity)) return p.activity as WhaleActivity[];
  if (event && Array.isArray(event.activity)) return event.activity as WhaleActivity[];
  if (event && Array.isArray(event)) return event as WhaleActivity[];
  return [];
}
