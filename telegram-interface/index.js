import express from "express";
import { Telegraf } from "telegraf";

const requiredEnv = [
  "TELEGRAM_BOT_TOKEN",
  "OPENWEBUI_BASE_URL",
  "OPENWEBUI_API_KEY",
  "OPENWEBUI_MODEL"
];

for (const k of requiredEnv) {
  if (!process.env[k] || String(process.env[k]).trim() === "") {
    console.error(`Missing required env var: ${k}`);
    process.exit(1);
  }
}

const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN.trim();
const OPENWEBUI_BASE_URL = process.env.OPENWEBUI_BASE_URL.trim().replace(/\/+$/, "");
const OPENWEBUI_API_KEY = process.env.OPENWEBUI_API_KEY.trim();
const OPENWEBUI_MODEL = process.env.OPENWEBUI_MODEL.trim();
const DEFAULT_SYSTEM_PROMPT =
  (process.env.SYSTEM_PROMPT || "You are a helpful, concise assistant.").trim();

const MAX_TURNS = Number(process.env.MAX_TURNS || 8);
const HEALTH_PORT = Number(process.env.HEALTH_PORT || 8081);

// Admins: comma-separated Telegram user IDs (from @userinfobot)
const ADMIN_USER_IDS = String(process.env.ADMIN_USER_IDS || "")
  .split(",")
  .map(s => s.trim())
  .filter(Boolean)
  .map(s => Number(s))
  .filter(n => Number.isFinite(n));

const bot = new Telegraf(TELEGRAM_BOT_TOKEN);

// Cache bot username once we have it
let BOT_USERNAME = null;

// Memory per-user-per-chat so groups don’t share one blob
// key: `${chatId}:${userId}` -> [{role, content}, ...]
const memory = new Map();

// Optional per-chat prompt overrides (admin-only)
const promptByChat = new Map();

function memKey(chatId, userId) {
  return `${chatId}:${userId}`;
}

function isGroup(chatType) {
  return chatType === "group" || chatType === "supergroup";
}

function isAdmin(ctx) {
  const uid = ctx.from?.id;
  return Boolean(uid && ADMIN_USER_IDS.includes(uid));
}

function getSystemPrompt(chatId) {
  return (promptByChat.get(chatId) || DEFAULT_SYSTEM_PROMPT).trim();
}

function getHistory(chatId, userId) {
  const key = memKey(chatId, userId);
  const arr = memory.get(key) || [];
  return arr.slice(-MAX_TURNS * 2);
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
  // wipe all keys starting with `${chatId}:`
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
  // In groups: respond only if
  // 1) mentioned by @username OR
  // 2) replying to a message from the bot OR
  // 3) command (starts with /)
  if (!isGroup(ctx.chat?.type)) return true;

  if (!text) return false;
  if (text.startsWith("/")) return true;

  const lowered = text.toLowerCase();
  if (BOT_USERNAME && lowered.includes(`@${BOT_USERNAME.toLowerCase()}`)) return true;

  const replyTo = ctx.message?.reply_to_message;
  const replyFrom = replyTo?.from;
  if (replyFrom?.is_bot && BOT_USERNAME && replyFrom?.username?.toLowerCase() === BOT_USERNAME.toLowerCase()) {
    return true;
  }

  return false;
}

async function callOpenWebUI(chatId, userId, userText) {
  const url = `${OPENWEBUI_BASE_URL}/api/chat/completions`;
  const messages = [
    { role: "system", content: getSystemPrompt(chatId) },
    ...getHistory(chatId, userId),
    { role: "user", content: userText }
  ];

  const resp = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${OPENWEBUI_API_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model: OPENWEBUI_MODEL,
      messages,
      stream: false
    })
  });

  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`OpenWebUI error ${resp.status}: ${text}`);
  }

  const data = await resp.json();
  const content =
    data?.choices?.[0]?.message?.content ??
    data?.message?.content ??
    data?.content ??
    "";

  return String(content).trim();
}

function chunkTelegram(text) {
  const chunks = [];
  const maxLen = 3500;
  for (let i = 0; i < text.length; i += maxLen) {
    chunks.push(text.slice(i, i + maxLen));
  }
  return chunks.length ? chunks : ["(empty response)"];
}

// ---- Commands ----

bot.start(async (ctx) => {
  const chatType = ctx.chat?.type || "unknown";
  await ctx.reply(
    `Online.\nModel: ${OPENWEBUI_MODEL}\nChat type: ${chatType}\n` +
    (isGroup(chatType)
      ? `Group mode: mention @${BOT_USERNAME || "this_bot"} or reply to me.`
      : `Send a message to chat.`)
  );
});

// /id — helpful in groups
bot.command("id", async (ctx) => {
  const chatId = ctx.chat?.id;
  const userId = ctx.from?.id;
  await ctx.reply(`chat_id: ${chatId}\nuser_id: ${userId}`);
});

// /reset — clears memory for YOU in this chat
bot.command("reset", async (ctx) => {
  const chatId = ctx.chat?.id;
  const userId = ctx.from?.id;
  if (chatId == null || userId == null) return;
  clearUserMemory(chatId, userId);
  await ctx.reply("Your memory is cleared for this chat.");
});

// /reset_chat — ADMIN ONLY — clears memory for everyone in this chat
bot.command("reset_chat", async (ctx) => {
  if (!isAdmin(ctx)) {
    await ctx.reply("Not authorized.");
    return;
  }
  const chatId = ctx.chat?.id;
  if (chatId == null) return;
  clearChatMemory(chatId);
  await ctx.reply("Chat memory cleared for everyone.");
});

// /setprompt <text> — ADMIN ONLY — overrides system prompt for this chat
bot.command("setprompt", async (ctx) => {
  if (!isAdmin(ctx)) {
    await ctx.reply("Not authorized.");
    return;
  }
  const chatId = ctx.chat?.id;
  if (chatId == null) return;

  const text = ctx.message?.text || "";
  const parts = text.split(" ").slice(1);
  const newPrompt = parts.join(" ").trim();

  if (!newPrompt) {
    await ctx.reply("Usage: /setprompt <new system prompt>");
    return;
  }

  promptByChat.set(chatId, newPrompt);
  await ctx.reply("System prompt updated for this chat.");
});

// /prompt — show current prompt (admin only, to avoid leaking)
bot.command("prompt", async (ctx) => {
  if (!isAdmin(ctx)) {
    await ctx.reply("Not authorized.");
    return;
  }
  const chatId = ctx.chat?.id;
  if (chatId == null) return;
  await ctx.reply(`Current system prompt:\n${getSystemPrompt(chatId)}`);
});

// /model — show model
bot.command("model", async (ctx) => {
  await ctx.reply(`Model: ${OPENWEBUI_MODEL}`);
});

// ---- Main message handler ----

bot.on("text", async (ctx) => {
  // ignore bot messages
  if (ctx.from?.is_bot) return;

  const chatId = ctx.chat?.id;
  const userId = ctx.from?.id;
  let text = ctx.message?.text?.trim();

  if (chatId == null || userId == null || !text) return;

  // Group mention-only logic
  if (isGroup(ctx.chat?.type)) {
    if (!shouldRespondInGroup(ctx, text)) return;
    text = stripMention(text);
    // If they only said "@bot" and nothing else, ignore
    if (!text || text.length < 1) return;
  }

  try { await ctx.sendChatAction("typing"); } catch {}

  try {
    const reply = await callOpenWebUI(chatId, userId, text);

    // Save memory per user per chat
    pushHistory(chatId, userId, "user", text);
    pushHistory(chatId, userId, "assistant", reply || "(no response)");

    for (const c of chunkTelegram(reply)) {
      await ctx.reply(c);
    }
  } catch (err) {
    console.error(err);
    await ctx.reply("AI server error. Check logs: docker logs -n 200 telegram-interface");
  }
});

// Health endpoint for Kuma
const app = express();
app.get("/health", (req, res) => res.status(200).send("ok"));
app.listen(HEALTH_PORT, "0.0.0.0", () => console.log(`Health listening on :${HEALTH_PORT}`));

// Launch + capture bot username
(async () => {
  try {
    await bot.launch();
    const me = await bot.telegram.getMe();
    BOT_USERNAME = me?.username || null;
    console.log(`Telegram bot launched as @${BOT_USERNAME || "unknown"}`);
  } catch (e) {
    console.error("Bot launch failed:", e);
    process.exit(1);
  }
})();

process.once("SIGINT", () => bot.stop("SIGINT"));
process.once("SIGTERM", () => bot.stop("SIGTERM"));
