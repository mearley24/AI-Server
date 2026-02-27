import express from "express";
import { Telegraf } from "telegraf";

// ---------------------------------------------------------------------------
// Environment validation
// ---------------------------------------------------------------------------
const requiredEnv = [
  "TELEGRAM_BOT_TOKEN",
  "OPENCLAW_URL",
];

for (const k of requiredEnv) {
  if (!process.env[k] || String(process.env[k]).trim() === "") {
    console.error(`Missing required env var: ${k}`);
    process.exit(1);
  }
}

const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN.trim();
const OPENCLAW_URL = process.env.OPENCLAW_URL.trim().replace(/\/+$/, "");
const REDIS_URL = (process.env.REDIS_URL || "").trim();
const LOG_LEVEL = (process.env.LOG_LEVEL || "info").trim();
const HEALTH_PORT = Number(process.env.HEALTH_PORT || 8081);

// Owner chat ID — restricts admin commands to the business owner
const OWNER_CHAT_ID = Number(
  (process.env.TELEGRAM_OWNER_CHAT_ID || "0").trim()
);

const MAX_TURNS = Number(process.env.MAX_TURNS || 12);

const bot = new Telegraf(TELEGRAM_BOT_TOKEN);
let BOT_USERNAME = null;

// Per-user-per-chat conversation memory
const memory = new Map();

function memKey(chatId, userId) {
  return `${chatId}:${userId}`;
}

function isGroup(chatType) {
  return chatType === "group" || chatType === "supergroup";
}

function isOwner(ctx) {
  return OWNER_CHAT_ID > 0 && ctx.from?.id === OWNER_CHAT_ID;
}

function getHistory(chatId, userId) {
  const key = memKey(chatId, userId);
  return (memory.get(key) || []).slice(-MAX_TURNS * 2);
}

function pushHistory(chatId, userId, role, content) {
  const key = memKey(chatId, userId);
  const arr = memory.get(key) || [];
  arr.push({ role, content });
  memory.set(key, arr.slice(-MAX_TURNS * 2));
}

function clearUserMemory(chatId, userId) {
  memory.delete(memKey(chatId, userId));
}

function clearChatMemory(chatId) {
  const prefix = `${chatId}:`;
  for (const k of memory.keys()) {
    if (k.startsWith(prefix)) memory.delete(k);
  }
}

function stripMention(text) {
  if (!BOT_USERNAME) return text;
  const re = new RegExp(`@${BOT_USERNAME}\\b`, "ig");
  return text.replace(re, "").trim();
}

function shouldRespondInGroup(ctx, text) {
  if (!isGroup(ctx.chat?.type)) return true;
  if (!text) return false;
  if (text.startsWith("/")) return true;
  const lowered = text.toLowerCase();
  if (BOT_USERNAME && lowered.includes(`@${BOT_USERNAME.toLowerCase()}`))
    return true;
  const replyTo = ctx.message?.reply_to_message;
  const replyFrom = replyTo?.from;
  if (
    replyFrom?.is_bot &&
    BOT_USERNAME &&
    replyFrom?.username?.toLowerCase() === BOT_USERNAME.toLowerCase()
  ) {
    return true;
  }
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
// OpenClaw API call
// ---------------------------------------------------------------------------
async function callOpenClaw(chatId, userId, userText, meta = {}) {
  const url = `${OPENCLAW_URL}/api/chat/completions`;

  const messages = [
    ...getHistory(chatId, userId),
    { role: "user", content: userText },
  ];

  const payload = {
    model: "bob_conductor",
    messages,
    stream: false,
    metadata: {
      source: "telegram",
      chat_id: chatId,
      user_id: userId,
      is_owner: OWNER_CHAT_ID > 0 && userId === OWNER_CHAT_ID,
      ...meta,
    },
  };

  log("debug", `OpenClaw request: ${userText.substring(0, 100)}`);

  const resp = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!resp.ok) {
    const errText = await resp.text().catch(() => "");
    throw new Error(`OpenClaw error ${resp.status}: ${errText}`);
  }

  const data = await resp.json();
  const content =
    data?.choices?.[0]?.message?.content ??
    data?.message?.content ??
    data?.content ??
    "";

  return String(content).trim();
}

// ---------------------------------------------------------------------------
// Telegram message chunking (max 4096 chars per message)
// ---------------------------------------------------------------------------
function chunkTelegram(text) {
  const chunks = [];
  const maxLen = 3500;
  for (let i = 0; i < text.length; i += maxLen) {
    chunks.push(text.slice(i, i + maxLen));
  }
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
      `Routed through: OpenClaw\n` +
      `Chat type: ${chatType}${owner}\n\n` +
      (isGroup(chatType)
        ? `Group mode: mention @${BOT_USERNAME || "ConductorBob_bot"} or reply to me.`
        : `Send a message or use /help for commands.`)
  );
});

bot.command("id", async (ctx) => {
  const chatId = ctx.chat?.id;
  const userId = ctx.from?.id;
  await ctx.reply(`chat_id: ${chatId}\nuser_id: ${userId}`);
});

bot.command("reset", async (ctx) => {
  const chatId = ctx.chat?.id;
  const userId = ctx.from?.id;
  if (chatId == null || userId == null) return;
  clearUserMemory(chatId, userId);
  await ctx.reply("Conversation memory cleared.");
});

bot.command("reset_chat", async (ctx) => {
  if (!isOwner(ctx)) {
    await ctx.reply("Not authorized.");
    return;
  }
  const chatId = ctx.chat?.id;
  if (chatId == null) return;
  clearChatMemory(chatId);
  await ctx.reply("Chat memory cleared for everyone.");
});

// All other /commands get forwarded to OpenClaw (Bob handles them)
const PASSTHROUGH_COMMANDS = [
  "status",
  "pipeline",
  "earnings",
  "client",
  "proposal",
  "dtools",
  "health",
  "schedule",
  "help",
  "digest",
  "log",
  "task",
  "alert",
  "model",
];

for (const cmd of PASSTHROUGH_COMMANDS) {
  bot.command(cmd, async (ctx) => {
    const chatId = ctx.chat?.id;
    const userId = ctx.from?.id;
    const text = ctx.message?.text?.trim();
    if (chatId == null || userId == null || !text) return;

    try {
      await ctx.sendChatAction("typing");
    } catch {}

    try {
      const reply = await callOpenClaw(chatId, userId, text, {
        is_command: true,
        command: `/${cmd}`,
      });

      pushHistory(chatId, userId, "user", text);
      pushHistory(chatId, userId, "assistant", reply || "(no response)");

      for (const c of chunkTelegram(reply)) {
        await ctx.reply(c);
      }
    } catch (err) {
      log("error", `Command /${cmd} error:`, err.message);
      await ctx.reply(
        `Error processing /${cmd}. Check Bob's logs: docker logs symphony_telegram_bot`
      );
    }
  });
}

// ---------------------------------------------------------------------------
// Main text message handler
// ---------------------------------------------------------------------------
bot.on("text", async (ctx) => {
  if (ctx.from?.is_bot) return;

  const chatId = ctx.chat?.id;
  const userId = ctx.from?.id;
  let text = ctx.message?.text?.trim();

  if (chatId == null || userId == null || !text) return;

  // Group mention-only logic
  if (isGroup(ctx.chat?.type)) {
    if (!shouldRespondInGroup(ctx, text)) return;
    text = stripMention(text);
    if (!text || text.length < 1) return;
  }

  try {
    await ctx.sendChatAction("typing");
  } catch {}

  try {
    const reply = await callOpenClaw(chatId, userId, text);

    pushHistory(chatId, userId, "user", text);
    pushHistory(chatId, userId, "assistant", reply || "(no response)");

    for (const c of chunkTelegram(reply)) {
      await ctx.reply(c);
    }
  } catch (err) {
    log("error", "Message handling error:", err.message);
    await ctx.reply(
      "OpenClaw is not responding. Check logs: docker logs symphony_openclaw"
    );
  }
});

// ---------------------------------------------------------------------------
// Health endpoint (Docker healthcheck)
// ---------------------------------------------------------------------------
const app = express();

app.get("/health", (req, res) => {
  res.status(200).json({
    status: "ok",
    bot: BOT_USERNAME || "starting",
    openclaw_url: OPENCLAW_URL,
    owner_configured: OWNER_CHAT_ID > 0,
    uptime_seconds: Math.floor(process.uptime()),
  });
});

app.listen(HEALTH_PORT, "0.0.0.0", () =>
  log("info", `Health endpoint listening on :${HEALTH_PORT}`)
);

// ---------------------------------------------------------------------------
// Launch
// ---------------------------------------------------------------------------
(async () => {
  try {
    await bot.launch();
    const me = await bot.telegram.getMe();
    BOT_USERNAME = me?.username || null;
    log("info", `Telegram bot launched as @${BOT_USERNAME || "unknown"}`);
    log("info", `OpenClaw endpoint: ${OPENCLAW_URL}`);
    log("info", `Owner chat ID: ${OWNER_CHAT_ID || "not configured"}`);
  } catch (e) {
    log("error", "Bot launch failed:", e);
    process.exit(1);
  }
})();

process.once("SIGINT", () => bot.stop("SIGINT"));
process.once("SIGTERM", () => bot.stop("SIGTERM"));
