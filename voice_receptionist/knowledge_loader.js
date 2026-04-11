/**
 * knowledge_loader.js — Reads Symphony project docs from iCloud mount
 * and builds a knowledge context string for the system prompt.
 *
 * Reads: /data/symphony_docs/ (mounted from iCloud SymphonySH folder)
 * Also reads: /data/voice-receptionist/learned_context.json (from cortex)
 *
 * Returns a string to append to the system prompt with:
 * - Active project summaries (from .md and .pdf filenames)
 * - Recent client interactions (from email-monitor Redis)
 * - Any cortex-provided context
 */

'use strict';

const fs   = require('fs');
const path = require('path');

const SYMPHONY_DOCS    = process.env.SYMPHONY_DOCS_PATH || '/data/symphony_docs';
const LEARNED_CONTEXT  = '/data/voice-receptionist/learned_context.json';

function loadKnowledge() {
  let context = '\n\n## Dynamic Knowledge (auto-loaded)\n\n';

  // 1. List active project folders/files from iCloud mount
  try {
    if (fs.existsSync(SYMPHONY_DOCS)) {
      const items = fs.readdirSync(SYMPHONY_DOCS, { recursive: true })
        .filter(f => !f.startsWith('.'))
        .slice(0, 50);  // Cap at 50 items
      if (items.length > 0) {
        context += '### Active Project Files\n';
        for (const item of items) {
          context += `- ${item}\n`;
        }
        context += '\n';
      }
    }
  } catch (e) {
    console.warn('[knowledge] Could not read symphony docs:', e.message);
  }

  // 2. Load cortex-provided learned context
  try {
    if (fs.existsSync(LEARNED_CONTEXT)) {
      const learned = JSON.parse(fs.readFileSync(LEARNED_CONTEXT, 'utf8'));
      if (learned.client_notes) {
        context += '### Client Notes\n';
        for (const [name, notes] of Object.entries(learned.client_notes)) {
          context += `- **${name}**: ${notes}\n`;
        }
        context += '\n';
      }
      if (learned.recent_emails) {
        context += '### Recent Client Emails (last 48h)\n';
        for (const em of learned.recent_emails.slice(0, 10)) {
          context += `- ${em.from}: ${em.subject} (${em.date})\n`;
        }
        context += '\n';
      }
    }
  } catch (e) {
    console.warn('[knowledge] Could not read learned context:', e.message);
  }

  return context;
}

// Reload every 6 hours
let cachedKnowledge = loadKnowledge();
setInterval(() => {
  cachedKnowledge = loadKnowledge();
  console.log('[knowledge] Refreshed knowledge context');
}, 6 * 60 * 60 * 1000);

module.exports = {
  getKnowledge: () => cachedKnowledge,
  reload: () => { cachedKnowledge = loadKnowledge(); },
};
