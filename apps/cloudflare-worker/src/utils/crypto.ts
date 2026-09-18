const encoder = new TextEncoder();

export async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function idempotencyKey(chain: string, txHash: string, logIndex: number): Promise<string> {
  if (!Number.isSafeInteger(logIndex) || logIndex < 0 || !chain || !txHash) {
    throw new Error("Invalid event identity");
  }
  return sha256(chain + txHash + logIndex);
}

export async function verifyHmac(raw: string, signature: string | undefined, secret: string | undefined): Promise<boolean> {
  if (!secret || !signature) return false;
  const hex = signature.replace(/^0x/i, "");
  if (!/^[a-f\d]{64}$/i.test(hex)) return false;
  const bytes = Uint8Array.from(hex.match(/.{2}/g)!, (byte) => Number.parseInt(byte, 16));
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
  return crypto.subtle.verify("HMAC", key, bytes, encoder.encode(raw));
}

export async function verifySecret(received: string | undefined, expected: string | undefined): Promise<boolean> {
  if (!received || !expected) return false;
  const key = await crypto.subtle.importKey("raw", encoder.encode(expected), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(expected));
  return crypto.subtle.verify("HMAC", key, signature, encoder.encode(received));
}
