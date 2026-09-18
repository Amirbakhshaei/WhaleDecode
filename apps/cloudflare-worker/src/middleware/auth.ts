import { MAX_BODY_BYTES } from "../config/constants";
import { verifyHmac, verifySecret } from "../utils/crypto";
import type { Env } from "../types";

export async function readBody(request: Request): Promise<string> {
  if (Number(request.headers.get("content-length")) > MAX_BODY_BYTES) throw new Error("body_too_large");
  const reader = request.body?.getReader();
  if (!reader) return "";
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BODY_BYTES) { await reader.cancel(); throw new Error("body_too_large"); }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return new TextDecoder().decode(bytes);
}

export async function alchemyAuth(raw: string, signature: string | undefined, env: Env): Promise<boolean> {
  const keys = [env.ALCHEMY_WEBHOOK_SIGNING_KEY, env.ALCHEMY_SIGNING_KEY_ETH, env.ALCHEMY_SIGNING_KEY_ARB, env.ALCHEMY_SIGNING_KEY_BASE,
    ...(env.ALCHEMY_WEBHOOK_SIGNING_KEYS ?? "").split(",")].filter((key): key is string => !!key);
  for (const key of new Set(keys)) if (await verifyHmac(raw, signature, key)) return true;
  return false;
}

export { verifySecret };
