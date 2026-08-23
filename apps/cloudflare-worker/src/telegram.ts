import type { AppConfig } from "./config";

const API = "https://api.telegram.org/bot";

export class TelegramClient {
  constructor(
    private cfg: AppConfig,
    private fetchFn: typeof fetch = fetch,
  ) {}

  private url(method: string): string {
    return `${API}${this.cfg.botToken}/${method}`;
  }

  async sendMessage(
    chatId: string,
    text: string,
    options: { parseMode?: "HTML" | "Markdown"; replyMarkup?: unknown } = {},
  ): Promise<{ ok: boolean; messageId?: number }> {
    const res = await this.fetchFn(this.url("sendMessage"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        text,
        parse_mode: options.parseMode || "HTML",
        disable_web_page_preview: true,
        reply_markup: options.replyMarkup,
      }),
    });
    const data = (await res.json()) as {
      ok: boolean;
      result?: { message_id: number };
      error_code?: number;
    };
    if (!data.ok) throw new Error(`Telegram sendMessage failed: ${data.error_code}`);
    return { ok: true, messageId: data.result?.message_id };
  }

  async editMessageText(
    chatId: string,
    messageId: number,
    text: string,
  ): Promise<void> {
    const res = await this.fetchFn(this.url("editMessageText"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        message_id: messageId,
        text,
        parse_mode: "HTML",
        disable_web_page_preview: true,
      }),
    });
    if (!res.ok) {
      const data = (await res.json().catch(() => ({}))) as { error_code?: number };
      if (data.error_code !== 400) {
        throw new Error(`Telegram editMessage failed: ${data.error_code}`);
      }
    }
  }
}
