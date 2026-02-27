/**
 * call_logger.js — Persist call events to SQLite
 *
 * Schema
 * ──────
 * calls(id, call_sid, client_id, caller_number, started_at, ended_at,
 *        duration_s, outcome, transcript_summary, technician_dispatched,
 *        notes, created_at)
 */

'use strict';

const Database = require('better-sqlite3');
const path = require('path');

const DB_PATH = process.env.DB_PATH || path.join(__dirname, 'data', 'bob.db');

let db;

function getDb() {
  if (!db) {
    db = new Database(DB_PATH);
    db.pragma('journal_mode = WAL');
    db.exec(`
      CREATE TABLE IF NOT EXISTS calls (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        call_sid             TEXT    NOT NULL UNIQUE,
        client_id            INTEGER,
        caller_number        TEXT,
        started_at           TEXT    NOT NULL,
        ended_at             TEXT,
        duration_s           INTEGER,
        outcome              TEXT,   -- 'resolved' | 'scheduled' | 'escalated' | 'unknown'
        transcript_summary   TEXT,
        technician_dispatched INTEGER DEFAULT 0,
        notes                TEXT,
        created_at           TEXT    NOT NULL DEFAULT (datetime('now'))
      );

      CREATE INDEX IF NOT EXISTS idx_calls_call_sid   ON calls(call_sid);
      CREATE INDEX IF NOT EXISTS idx_calls_client_id  ON calls(client_id);
      CREATE INDEX IF NOT EXISTS idx_calls_started_at ON calls(started_at);
    `);
  }
  return db;
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Open a new call record.
 * @param {string} callSid   Twilio CallSid
 * @param {string} callerNum Caller's phone number (E.164)
 * @returns {number}         New row id
 */
function openCall(callSid, callerNum) {
  const stmt = getDb().prepare(`
    INSERT INTO calls (call_sid, caller_number, started_at)
    VALUES (@callSid, @callerNum, @startedAt)
  `);
  const result = stmt.run({
    callSid,
    callerNum,
    startedAt: new Date().toISOString(),
  });
  return result.lastInsertRowid;
}

/**
 * Attach a resolved client to a call.
 */
function attachClient(callSid, clientId) {
  getDb()
    .prepare('UPDATE calls SET client_id = ? WHERE call_sid = ?')
    .run(clientId, callSid);
}

/**
 * Close a call and record the outcome.
 * @param {string} callSid
 * @param {object} opts
 * @param {string}  opts.outcome            'resolved'|'scheduled'|'escalated'|'unknown'
 * @param {string}  [opts.transcriptSummary]
 * @param {boolean} [opts.technicianDispatched]
 * @param {string}  [opts.notes]
 */
function closeCall(callSid, { outcome, transcriptSummary, technicianDispatched, notes } = {}) {
  const endedAt = new Date().toISOString();
  getDb()
    .prepare(`
      UPDATE calls
      SET ended_at = @endedAt,
          duration_s = CAST((julianday(@endedAt) - julianday(started_at)) * 86400 AS INTEGER),
          outcome = @outcome,
          transcript_summary = @transcriptSummary,
          technician_dispatched = @technicianDispatched,
          notes = @notes
      WHERE call_sid = @callSid
    `)
    .run({
      endedAt,
      outcome: outcome || 'unknown',
      transcriptSummary: transcriptSummary || null,
      technicianDispatched: technicianDispatched ? 1 : 0,
      notes: notes || null,
      callSid,
    });
}

/**
 * Fetch all calls for a given date (YYYY-MM-DD in UTC).
 */
function getCallsByDate(date) {
  return getDb()
    .prepare(`SELECT * FROM calls WHERE date(started_at) = ? ORDER BY started_at`)
    .all(date);
}

/**
 * Fetch the most recent N calls.
 */
function getRecentCalls(limit = 20) {
  return getDb()
    .prepare(`SELECT * FROM calls ORDER BY started_at DESC LIMIT ?`)
    .all(limit);
}

module.exports = { openCall, attachClient, closeCall, getCallsByDate, getRecentCalls };
