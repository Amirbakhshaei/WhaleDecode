import { Hono } from "hono";
import type { Env } from "./types";
import { alchemyRouter } from "./routes/alchemy";
import { telegramRouter } from "./routes/telegram";

const app = new Hono<{ Bindings: Env }>();

app.get("/", (c) => c.text("WhaleDecode Edge Worker Live"));

app.route("/webhook/alchemy", alchemyRouter);
app.route("/webhook/telegram", telegramRouter);

app.notFound((c) =>
  c.json({ error: "not_found", path: c.req.path }, 404),
);

app.onError((err, c) => {
  console.error("worker_error", { message: String(err?.message ?? err) });
  return c.json(
    { error: "internal_error", message: String(err?.message ?? err) },
    500,
  );
});

export default app;
