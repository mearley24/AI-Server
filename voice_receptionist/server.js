/**
 * server.js — Bob the Conductor: AI Voice Receptionist
 *
 * Bridges Twilio Media Streams (WebSocket, mulaw 8kHz audio) to the
 * OpenAI Realtime API (gpt-4o-realtime-preview) for live bidirectional
 * voice conversations.
 *
 * Endpoints
 * ─────────
 * POST /incoming-call    Twilio Voice webhook → returns TwiML
 * GET  /health           Health check (Docker, load balancer)
 * WS   /media-stream     Twilio media-stream WebSocket
 */

'use strict';

require('dotenv').config();

const express    = require('express');
const http       = require('http');
const { WebSocketServer, WebSocket } = require('ws');
const fs         = require('fs');
const path       = require('path');

const clientLookup  = require('./client_lookup');
const troubleshoot  = require('./troubleshoot');
const scheduler     = require('./scheduler');
const callLogger    = require('./call_logger');

// ─── Config ───────────────────────────────────────────────────────────────────

const PORT       = parseInt(process.env.PORT || '3000', 10);
const SERVER_URL = process.env.SERVER_URL || `http://localhost:${PORT}`;
const OPENAI_KEY = process.env.OPENAI_API_KEY;
const SYSTEM_PROMPT = fs.readFileSync(path.join(__dirname, 'system_prompt.md'), 'utf8');

if (!OPENAI_KEY) throw new Error('OPENAI_API_KEY is required');

// ─── Express app ─────────────────────────────────────────────────────────────

const app    = express();
const server = http.createServer(app);

app.use(express.urlencoded({ extended: false }));
app.use(express.json());

// Health check
app.get('/health', (_req, res) => res.json({ status: 'ok', ts: new Date().toISOString() }));

// Twilio Voice webhook — returns TwiML that opens a media stream
app.post('/incoming-call', (req, res) => {
  const callerNum = req.body.From || 'Unknown';
  console.log(`[bob] Incoming call from ${callerNum}`);

  const wsUrl = SERVER_URL.replace(/^http/, 'ws') + '/media-stream';
  const twiml = `<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="${wsUrl}">
      <Parameter name="callerNumber" value="${callerNum}" />
    </Stream>
  </Connect>
</Response>`;

  res.type('text/xml').send(twiml);
});

// ─── WebSocket server ─────────────────────────────────────────────────────────

const wss = new WebSocketServer({ server, path: '/media-stream' });

wss.on('connection', async (twilioWs, req) => {
  console.log('[bob] Media stream connected');

  let callSid        = null;
  let callerNumber   = null;
  let openaiWs       = null;
  let streamSid      = null;
  let callRowId      = null;
  let clientRecord   = null;

  // ── Open OpenAI Realtime connection ────────────────────────────────────────
  openaiWs = new WebSocket(
    'wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01',
    {
      headers: {
        Authorization: `Bearer ${OPENAI_KEY}`,
        'OpenAI-Beta': 'realtime=v1',
      },
    }
  );

  openaiWs.on('open', () => {
    console.log('[bob] OpenAI Realtime connected');
    // Send session config
    openaiWs.send(JSON.stringify({
      type: 'session.update',
      session: {
        turn_detection:    { type: 'server_vad' },
        input_audio_format:  'g711_ulaw',
        output_audio_format: 'g711_ulaw',
        voice: 'alloy',
        instructions: SYSTEM_PROMPT,
        modalities: ['text', 'audio'],
        temperature: 0.7,
      },
    }));
  });

  // ── Route OpenAI → Twilio ──────────────────────────────────────────────────
  openaiWs.on('message', (rawMsg) => {
    const msg = JSON.parse(rawMsg);

    if (msg.type === 'response.audio.delta' && msg.delta && streamSid) {
      twilioWs.send(JSON.stringify({
        event: 'media',
        streamSid,
        media: { payload: msg.delta },
      }));
    }

    // Tool calls from the model
    if (msg.type === 'response.function_call_arguments.done') {
      handleToolCall(msg).catch(console.error);
    }
  });

  openaiWs.on('error', (err) => console.error('[bob] OpenAI WS error:', err));
  openaiWs.on('close', () => console.log('[bob] OpenAI WS closed'));

  // ── Route Twilio → OpenAI ──────────────────────────────────────────────────
  twilioWs.on('message', (rawMsg) => {
    const msg = JSON.parse(rawMsg);

    switch (msg.event) {
      case 'start': {
        streamSid    = msg.start.streamSid;
        callSid      = msg.start.callSid;
        callerNumber = msg.start.customParameters?.callerNumber || 'Unknown';
        callRowId    = callLogger.openCall(callSid, callerNumber);

        // Async: try to resolve client from phone number
        clientRecord = clientLookup.findByPhone(callerNumber);
        if (clientRecord) {
          callLogger.attachClient(callSid, clientRecord.id);
          // Inject context message so Bob knows who's calling
          openaiWs.send(JSON.stringify({
            type: 'conversation.item.create',
            item: {
              type: 'message',
              role: 'user',
              content: [{
                type: 'input_text',
                text: `[SYSTEM] Caller identified: ${clientRecord.name}, tier: ${clientRecord.tier}. Address: ${clientRecord.address || 'unknown'}. Notes: ${clientRecord.notes || 'none'}.`,
              }],
            },
          }));
        }

        console.log(`[bob] Stream started | SID: ${streamSid} | Caller: ${callerNumber}`);
        break;
      }

      case 'media':
        if (openaiWs?.readyState === WebSocket.OPEN) {
          openaiWs.send(JSON.stringify({
            type: 'input_audio_buffer.append',
            audio: msg.media.payload,
          }));
        }
        break;

      case 'stop':
        console.log('[bob] Media stream stopped');
        callLogger.closeCall(callSid, { outcome: 'unknown' });
        openaiWs?.close();
        break;
    }
  });

  twilioWs.on('close', () => {
    console.log('[bob] Twilio WS closed');
    if (callSid) callLogger.closeCall(callSid, { outcome: 'unknown' });
    openaiWs?.close();
  });

  // ─── Tool call handler ────────────────────────────────────────────────────

  async function handleToolCall(msg) {
    const fnName = msg.name;
    const args   = JSON.parse(msg.arguments);

    let result;

    if (fnName === 'lookup_client') {
      result = clientLookup.findByName(args.name) || clientLookup.findByPhone(args.phone);
    } else if (fnName === 'start_troubleshoot') {
      result = troubleshoot.startTree(args.category);
    } else if (fnName === 'troubleshoot_step') {
      result = troubleshoot.nextStep(args.tree_id, args.answer);
    } else if (fnName === 'schedule_service_call') {
      result = await scheduler.scheduleServiceCall(args);
    } else {
      result = { error: `Unknown function: ${fnName}` };
    }

    openaiWs.send(JSON.stringify({
      type:          'conversation.item.create',
      item: {
        type:       'function_call_output',
        call_id:    msg.call_id,
        output:     JSON.stringify(result),
      },
    }));
    openaiWs.send(JSON.stringify({ type: 'response.create' }));
  }
});

// ─── Start ────────────────────────────────────────────────────────────────────

server.listen(PORT, () => {
  console.log(`[bob] Listening on port ${PORT}`);
  console.log(`[bob] Public URL: ${SERVER_URL}`);
});
