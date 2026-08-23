import type { Env } from "./types";

export async function sendMessage(
  env: Env,
  chatId: string | number,
  text: string,
): Promise<void> {
  const res = await fetch(
    `https://api.telegram.org/bot${env.BOT_TOKEN}/sendMessage`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        text,
        parse_mode: "HTML",
        disable_web_page_preview: true,
      }),
    },
  );
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Telegram sendMessage ${res.status}: ${body.slice(0, 200)}`);
  }
}

export function sendToChannel(env: Env, text: string): Promise<void> {
  return sendMessage(env, env.CHANNEL_CHAT_ID, text);
}
