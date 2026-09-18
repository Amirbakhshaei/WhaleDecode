import crypto from "node:crypto";
import { xPublishEnabled } from "../config.js";

const X_API_KEY = process.env.X_API_KEY ?? "";
const X_API_SECRET = process.env.X_API_SECRET ?? "";
const X_ACCESS_TOKEN = process.env.X_ACCESS_TOKEN ?? "";
const X_ACCESS_SECRET = process.env.X_ACCESS_SECRET ?? "";

export function isXPublishEnabled(): boolean {
  return xPublishEnabled() && X_API_KEY.length > 0 && X_API_SECRET.length > 0 && X_ACCESS_TOKEN.length > 0 && X_ACCESS_SECRET.length > 0;
}

function percentEncode(s: string): string {
  return encodeURIComponent(s).replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
}

export function oauth1Header(method: string, url: string, creds: {
  apiKey: string; apiSecret: string; accessToken: string; accessSecret: string;
}): string {
  const nonce = crypto.randomBytes(16).toString("hex");
  const ts = Math.floor(Date.now() / 1000).toString();
  const oauth = {
    oauth_consumer_key: creds.apiKey,
    oauth_nonce: nonce,
    oauth_signature_method: "HMAC-SHA1",
    oauth_timestamp: ts,
    oauth_token: creds.accessToken,
    oauth_version: "1.0",
  };
  const baseUrl = url.split("?")[0]!;
  const params = new URLSearchParams(url.includes("?") ? url.split("?")[1]! : "");
  const pairs = [...Object.entries(oauth), ...[...params.entries()]]
    .map(([k, v]) => [percentEncode(k), percentEncode(v)] as const)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  const paramStr = pairs.map(([k, v]) => `${k}=${v}`).join("&");
  const sigBase = `${method.toUpperCase()}&${percentEncode(baseUrl)}&${percentEncode(paramStr)}`;
  const key = `${percentEncode(creds.apiSecret)}&${percentEncode(creds.accessSecret)}`;
  const sig = crypto.createHmac("sha1", key).update(sigBase).digest("base64");
  const header = {
    ...oauth,
    oauth_signature: sig,
  };
  return `OAuth ${Object.entries(header).map(([k, v]) => `${percentEncode(k)}="${percentEncode(v)}"`).join(", ")}`;
}

export async function publishThread(tweets: string[]): Promise<{ published: boolean; ids: string[] }> {
  if (!isXPublishEnabled()) return { published: false, ids: [] };
  const ids: string[] = [];
  let replyTo: string | undefined;
  for (const text of tweets) {
    const res = await fetch("https://api.twitter.com/2/tweets", {
      method: "POST",
      headers: {
        authorization: oauth1Header("POST", "https://api.twitter.com/2/tweets", {
          apiKey: X_API_KEY, apiSecret: X_API_SECRET, accessToken: X_ACCESS_TOKEN, accessSecret: X_ACCESS_SECRET,
        }),
        "content-type": "application/json",
      },
      body: JSON.stringify({ text, ...(replyTo ? { reply: { in_reply_to_tweet_id: replyTo } } : {}) }),
    });
    if (!res.ok) throw new Error(`x publish failed: ${res.status}`);
    const j = (await res.json()) as { data?: { id?: string } };
    replyTo = j.data?.id;
    if (replyTo) ids.push(replyTo);
  }
  return { published: true, ids };
}
