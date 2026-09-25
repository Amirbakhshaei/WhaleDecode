export type LogLevel = "DEBUG" | "INFO" | "WARN" | "ERROR";

export interface LogContext {
  chain?: string;
  txHash?: string;
  whale?: string;
  usdValue?: number;
  stage?: "INGRESS" | "BLACKLIST" | "GATED" | "DEDUP" | "ORACLE" | "AI_REASONING" | "ALERT";
  [key: string]: unknown;
}

function write(level: LogLevel, message: string, ctx: LogContext = {}): void {
  const entry = JSON.stringify({ timestamp: new Date().toISOString(), level, message, ...ctx });
  if (level === "ERROR") console.error(entry);
  else if (level === "WARN") console.warn(entry);
  else console.log(entry);
}

export const logger = {
  log: write,
  info: (msg: string, ctx?: LogContext) => write("INFO", msg, ctx),
  warn: (msg: string, ctx?: LogContext) => write("WARN", msg, ctx),
  error: (msg: string, ctx?: LogContext) => write("ERROR", msg, ctx),
  debug: (msg: string, ctx?: LogContext) => write("DEBUG", msg, ctx),
};
