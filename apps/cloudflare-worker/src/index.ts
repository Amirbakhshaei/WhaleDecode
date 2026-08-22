import { Hono } from "hono";

const app = new Hono();

app.get("/", (c) => {
  return c.text("WhaleDecode Worker is running!");
});

export default app;
