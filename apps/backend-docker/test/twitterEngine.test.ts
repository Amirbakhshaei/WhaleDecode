import assert from "node:assert/strict";
import { test } from "node:test";
import { oauth1Header, isXPublishEnabled } from "../src/services/twitterEngine.js";

test("oauth1 header is well-formed HMAC-SHA1 signature", () => {
  const h = oauth1Header("POST", "https://api.twitter.com/2/tweets", {
    apiKey: "key", apiSecret: "secret", accessToken: "token", accessSecret: "tokensecret",
  });
  assert.ok(h.startsWith("OAuth "));
  assert.ok(h.includes('oauth_signature_method="HMAC-SHA1"'));
  const sig = /oauth_signature="([^"]+)"/.exec(h)?.[1] ?? "";
  assert.ok(sig.length > 20);
  assert.ok(!sig.includes("&"));
});

test("X publishing disabled without env gate + creds", () => {
  delete process.env.X_PUBLISH_ENABLED;
  delete process.env.X_API_KEY;
  delete process.env.X_API_SECRET;
  delete process.env.X_ACCESS_TOKEN;
  delete process.env.X_ACCESS_SECRET;
  assert.equal(isXPublishEnabled(), false);
});
