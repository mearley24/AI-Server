import express from "express";
import { Telegraf } from "telegraf";

// ---------------------------------------------------------------------------
// Environment validation
// ---------------------------------------------------------------------------
const requiredEnv = [
  "TELEGRAM_BOT_TOKEN",
];

for (const k of requiredEnv) {
  if (!process.env[k] || String(process.env[k]).trim() === "") {
    console.error(`Missing required env var: ${k}`);
    process.exit(1);
  }
}

const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN.trim();
const HEALTH_PORT = Number(process.env.HEALTH_PORT || 8081);
const LOG_LEVEL = (process.env.LOG_LEVEL || "info").trim();
const MAX_TURNS = Number(process.env.MAX_TURNS || 12);

// Owner chat ID — restricts admin commands to the business owner
const OWNER_CHAT_ID = Number(
  (process.env.TELEGRAM_OWNER_CHAT_ID || "0").trim()
);

// ---------------------------------------------------------------------------
// AI Backend — supports Open WebUI now, OpenClaw later
// Priority: OPENCLAW_URL > OPENWEBUI_BASE_URL
// ---------------------------------------------------------------------------
const OPENCLAW_URL = (process.env.OPENCLAW_URL || "").trim().replace(/\/+$/, "");
const OPENWEBUI_BASE_URL = (process.env.OPENWEBUI_BASE_URL || "http://host.docker.internal:3000").trim().replace(/\/+$/, "");
const OPENWEBUI_API_KEY = (process.env.OPENWEBUI_API_KEY || "").trim();
const OPENWEBUI_MODEL = (process.env.OPENWEBUI_MODEL || "").trim();

// Determine which backend to use
const USE_OPENCLAW = OPENCLAW_URL.length > 0;
const AI_URL = USE_OPENCLAW ? OPENCLAW_URL : OPENWEBUI_BASE_URL;
const AI_BACKEND = USE_OPENCLAW ? "OpenClaw" : "Open WebUI";

const DEFAULT_SYSTEM_PROMPT = (process.env.SYSTEM_PROMPT || `You are Bob, the Conductor of Symphony Smart Homes — an AI orchestrator for a residential and commercial AV/automation integration company.

You are the primary intelligence managing this business. You:
- Answer questions about smart home technology (Control4, Lutron, Sonos, Araknis, Luma, Alarm.com)
- Help with business operations, scheduling, and client communications
- Provide concise, actionable responses — the owner is often on a job site
- Can discuss D-Tools projects, proposals, and pipeline when asked
- Flag urgent items clearly

Be concise. Use bullet points. No fluff.`).trim();

const bot = new Telegraf(TELEGRAM_BOT_TOKEN);
let BOT_USERNAME = null;

// Per-user-per-chat conversation memory
const memory = new Map();

function memKey(chatId, userId) { return `${chatId}:${userId}`; }
function isGroup(t) { return t === "group" || t === "supergroup"; }
function isOwner(ctx) { return OWNER_CHAT_ID > 0 && ctx.from?.id === OWNER_CHAT_ID; }

function getHistory(chatId, userId) {
  return (memory.get(memKey(chatId, userId)) || []).slice(-MAX_TURNS * 2);
}

function pushHistory(chatId, userId, role, content) {
  const key = memKey(chatId, userId);
  const arr = memory.get(key) || [];
  arr.push({ role, content });
  memory.set(key, arr.slice(-MAX_TURNS * 2));
}

function clearUserMemory(chatId, userId) { memory.delete(memKey(chatId, userId)); }
function clearChatMemory(chatId) {
  const prefix = `${chatId}:`;
  for (const k of memory.keys()) { if (k.startsWith(prefix)) memory.delete(k); }
}

function stripMention(text) {
  if (!BOT_USERNAME) return text;
  return text.replace(new RegExp(`@${BOT_USERNAME}\\b`, "ig"), "").trim();
}

function shouldRespondInGroup(ctx, text) {
  if (!isGroup(ctx.chat?.type)) return true;
  if (!text) return false;
  if (text.startsWith("/")) return true;
  if (BOT_USERNAME && text.toLowerCase().includes(`@${BOT_USERNAME.toLowerCase()}`)) return true;
  const rf = ctx.message?.reply_to_message?.from;
  if (rf?.is_bot && BOT_USERNAME && rf?.username?.toLowerCase() === BOT_USERNAME.toLowerCase()) return true;
  return false;
}

function log(level, ...args) {
  const levels = { error: 0, warn: 1, info: 2, debug: 3 };
  if ((levels[level] ?? 2) <= (levels[LOG_LEVEL] ?? 2)) {
    const ts = new Date().toISOString();
    console[level === "error" ? "error" : "log"](`[${ts}] [${level}]`, ...args);
  }
}

// ---------------------------------------------------------------------------
// AI Backend call — works with both Open WebUI and OpenClaw
// ---------------------------------------------------------------------------
async function callAI(chatId, userId, userText, meta = {}) {
  const url = `${AI_URL}/api/chat/completions`;

  const messages = [
    { role: "system", content: DEFAULT_SYSTEM_PROMPT },
    ...getHistory(chatId, userId),
    { role: "user", content: userText },
  ];

  const headers = { "Content-Type": "application/json" };
  if (!USE_OPENCLAW && OPENWEBUI_API_KEY) {
    headers["Authorization"] = `Bearer ${OPENWEBUI_API_KEY}`;
  }

  const payload = {
    model: USE_OPENCLAW ? "bob_conductor" : (OPENWEBUI_MODEL || "llama3"),
    messages,
    stream: false,
  };

  if (USE_OPENCLAW) {
    payload.metadata = {
      source: "telegram",
      chat_id: chatId,
      user_id: userId,
      is_owner: OWNER_CHAT_ID > 0 && userId === OWNER_CHAT_ID,
      ...meta,
    };
  }

  log("debug", `${AI_BACKEND} request: ${userText.substring(0, 80)}`);

  const resp = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });

  if (!resp.ok) {
    const errText = await resp.text().catch(() => "");
    throw new Error(`${AI_BACKEND} error ${resp.status}: ${errText}`);
  }

  const data = await resp.json();
  const content =
    data?.choices?.[0]?.message?.content ??
    data?.message?.content ??
    data?.content ?? "";

  return String(content).trim();
}

// ---------------------------------------------------------------------------
// Telegram chunking
// ---------------------------------------------------------------------------
function chunkTelegram(text) {
  const chunks = [];
  for (let i = 0; i < text.length; i += 3500) chunks.push(text.slice(i, i + 3500));
  return chunks.length ? chunks : ["(empty response)"];
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------
bot.start(async (ctx) => {
  const chatType = ctx.chat?.type || "unknown";
  const owner = isOwner(ctx) ? " (Owner)" : "";
  await ctx.reply(
    `Bob \u2014 The Conductor is online.\n` +
    `Backend: ${AI_BACKEND}\n` +
    `Chat type: ${chatType}${owner}\n\n` +
    (isGroup(chatType)
      ? `Group mode: mention @${BOT_USERNAME || "ConductorBob_bot"} or reply to me.`
      : `Send a message or use /help for commands.`)
  );
});

bot.command("id", async (ctx) => {
  await ctx.reply(`chat_id: ${ctx.chat?.id}\nuser_id: ${ctx.from?.id}`);
});

bot.command("reset", async (ctx) => {
  if (ctx.chat?.id != null && ctx.from?.id != null) {
    clearUserMemory(ctx.chat.id, ctx.from.id);
    await ctx.reply("Conversation memory cleared.");
  }
});

bot.command("reset_chat", async (ctx) => {
  if (!isOwner(ctx)) { await ctx.reply("Not authorized."); return; }
  if (ctx.chat?.id != null) {
    clearChatMemory(ctx.chat.id);
    await ctx.reply("Chat memory cleared for everyone.");
  }
});

bot.command("backend", async (ctx) => {
  await ctx.reply(
    `Backend: ${AI_BACKEND}\n` +
    `URL: ${AI_URL}\n` +
    (USE_OPENCLAW ? "" : `Model: ${OPENWEBUI_MODEL || "llama3"}\n`) +
    `Owner configured: ${OWNER_CHAT_ID > 0 ? "yes" : "no"}`
  );
});

// ---------------------------------------------------------------------------
// Main text handler — everything goes to AI backend
// ---------------------------------------------------------------------------
bot.on("text", async (ctx) => {
  if (ctx.from?.is_bot) return;
  const chatId = ctx.chat?.id;
  const userId = ctx.from?.id;
  let text = ctx.message?.text?.trim();
  if (chatId == null || userId == null || !text) return;

  if (isGroup(ctx.chat?.type)) {
    if (!shouldRespondInGroup(ctx, text)) return;
    text = stripMention(text);
    if (!text) return;
  }

  try { await ctx.sendChatAction("typing"); } catch {}

  try {
    const reply = await callAI(chatId, userId, text);
    pushHistory(chatId, userId, "user", text);
    pushHistory(chatId, userId, "assistant", reply || "(no response)");
    for (const c of chunkTelegram(reply)) await ctx.reply(c);
  } catch (err) {
    log("error", "Message error:", err.message);
    await ctx.reply(`${AI_BACKEND} error. Check logs:\ndocker logs symphony_telegram_bot`);
  }
});

// ---------------------------------------------------------------------------
// Health endpoint
// ---------------------------------------------------------------------------
const app = express();
app.get("/health", (req, res) => {
  res.status(200).json({
    status: "ok",
    bot: BOT_USERNAME || "starting",
    backend: AI_BACKEND,
    backend_url: AI_URL,
    owner_configured: OWNER_CHAT_ID > 0,
    uptime_seconds: Math.floor(process.uptime()),
  });
});
app.listen(HEALTH_PORT, "0.0.0.0", () =>
  log("info", `Health on :${HEALTH_PORT}`)
);

// ---------------------------------------------------------------------------
// Launch
// ---------------------------------------------------------------------------
(async () => {
  try {
    await bot.launch();
    const me = await bot.telegram.getMe();
    BOT_USERNAME = me?.username || null;
    log("info", `Bot launched as @${BOT_USERNAME || "unknown"}`);
    log("info", `Backend: ${AI_BACKEND} at ${AI_URL}`);
    log("info", `Owner: ${OWNER_CHAT_ID || "not set"}`);
  } catch (e) {
    log("error", "Launch failed:", e);
    process.exit(1);
  }
})();

process.once("SIGINT", () => bot.stop("SIGINT"));
process.once("SIGTERM", () => bot.stop("SIGTERM"));
