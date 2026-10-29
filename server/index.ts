import Anthropic from "@anthropic-ai/sdk";
import { betaZodOutputFormat } from "@anthropic-ai/sdk/helpers/beta/zod";
import express from "express";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import { ANNOUNCE_SYSTEM, CONCIERGE_SYSTEM, TRIAGE_SYSTEM } from "./prompts";

const MODEL = "claude-opus-5-5";
// 拒否（refusal）時にサーバー側で推奨モデルへ自動フォールバックさせる
const FALLBACK = {
  betas: ["server-side-fallback-2026-07-01"] as Anthropic.Beta.AnthropicBeta[],
  fallbacks: "default" as const,
};

const aiEnabled = Boolean(process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN);
const client = aiEnabled ? new Anthropic() : null;

const app = express();
app.use(express.json({ limit: "200kb" }));

app.get("/api/health", (_req, res) => {
  res.json({ ok: true, ai: aiEnabled });
});

const ChatBody = z.object({
  messages: z
    .array(z.object({ role: z.enum(["user", "assistant"]), content: z.string().min(1).max(4000) }))
    .min(1)
    .max(40),
  context: z.string().max(8000),
});

// 来場者向けAIコンシェルジュ（SSEでストリーミング）
app.post("/api/chat", async (req, res) => {
  if (!client) return res.status(503).json({ error: "ai_disabled" });
  const parsed = ChatBody.safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: "bad_request" });
  const { messages, context } = parsed.data;

  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  const send = (data: unknown) => res.write(`data: ${JSON.stringify(data)}\n\n`);

  const abort = new AbortController();
  res.on("close", () => abort.abort());

  try {
    const stream = client.beta.messages.stream(
      {
        model: MODEL,
        max_tokens: 4000,
        ...FALLBACK,
        output_config: { effort: "low" },
        system: [{ type: "text", text: CONCIERGE_SYSTEM, cache_control: { type: "ephemeral" } }],
        messages: [...messages, { role: "system", content: `# 現在の状況\n${context}` }],
      },
      { signal: abort.signal },
    );
    for await (const event of stream) {
      if (event.type === "content_block_delta" && event.delta.type === "text_delta") {
        send({ type: "text", text: event.delta.text });
      }
    }
    const final = await stream.finalMessage();
    if (final.stop_reason === "refusal") send({ type: "refusal" });
    send({ type: "done" });
  } catch (err) {
    if (!abort.signal.aborted) {
      console.error("[chat]", err instanceof Anthropic.APIError ? `${err.status} ${err.message}` : err);
      send({ type: "error" });
    }
  } finally {
    res.end();
  }
});

const TriageSchema = z.object({
  category: z.enum(["medical", "lost", "facility", "program", "accessibility", "other"]),
  urgency: z.enum(["high", "medium", "low"]),
  summary: z.string(),
  suggestedReply: z.string(),
});

// 運営向け：問い合わせの自動振り分け
app.post("/api/triage", async (req, res) => {
  if (!client) return res.status(503).json({ error: "ai_disabled" });
  const text = z.string().min(1).max(2000).safeParse(req.body?.text);
  if (!text.success) return res.status(400).json({ error: "bad_request" });
  try {
    const response = await client.beta.messages.parse({
      model: MODEL,
      max_tokens: 2000,
      ...FALLBACK,
      output_config: { effort: "low", format: betaZodOutputFormat(TriageSchema) },
      system: TRIAGE_SYSTEM,
      messages: [{ role: "user", content: text.data }],
    });
    if (response.stop_reason === "refusal" || !response.parsed_output) return res.status(502).json({ error: "no_result" });
    res.json({ ...response.parsed_output, source: "ai" });
  } catch (err) {
    console.error("[triage]", err instanceof Anthropic.APIError ? `${err.status} ${err.message}` : err);
    res.status(502).json({ error: "upstream" });
  }
});

const AnnounceSchema = z.object({ ja: z.string(), en: z.string() });

// 運営向け：メモから日英アナウンス文を生成
app.post("/api/announce", async (req, res) => {
  if (!client) return res.status(503).json({ error: "ai_disabled" });
  const note = z.string().min(1).max(1000).safeParse(req.body?.note);
  if (!note.success) return res.status(400).json({ error: "bad_request" });
  try {
    const response = await client.beta.messages.parse({
      model: MODEL,
      max_tokens: 2000,
      ...FALLBACK,
      output_config: { effort: "low", format: betaZodOutputFormat(AnnounceSchema) },
      system: ANNOUNCE_SYSTEM,
      messages: [{ role: "user", content: note.data }],
    });
    if (response.stop_reason === "refusal" || !response.parsed_output) return res.status(502).json({ error: "no_result" });
    res.json(response.parsed_output);
  } catch (err) {
    console.error("[announce]", err instanceof Anthropic.APIError ? `${err.status} ${err.message}` : err);
    res.status(502).json({ error: "upstream" });
  }
});

// 本番：ビルド済みフロントエンドを配信
const dist = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../dist");
if (process.env.NODE_ENV === "production" && fs.existsSync(dist)) {
  app.use(express.static(dist));
  app.get(/^(?!\/api).*/, (_req, res) => res.sendFile(path.join(dist, "index.html")));
}

const port = Number(process.env.PORT ?? 8787);
app.listen(port, () => {
  console.log(`API server on http://localhost:${port} (AI: ${aiEnabled ? "Claude" : "local fallback"})`);
});
