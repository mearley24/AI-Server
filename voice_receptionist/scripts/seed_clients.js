#!/usr/bin/env node
/**
 * scripts/seed_clients.js — Populate the SQLite client database
 *
 * Reads data/clients.json and upserts all records.
 * Safe to run multiple times (skips duplicates by phone).
 *
 * Usage:
 *   node scripts/seed_clients.js
 */

'use strict';

require('dotenv').config({ path: require('path').join(__dirname, '..', '.env') });

const path  = require('path');
const fs    = require('fs');
const Database = require('better-sqlite3');

const DB_PATH   = process.env.DB_PATH || path.join(__dirname, '..', 'data', 'bob.db');
const JSON_PATH = path.join(__dirname, '..', 'data', 'clients.json');

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');

// Ensure table exists
db.exec(`
  CREATE TABLE IF NOT EXISTS clients (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    phone      TEXT,
    address    TEXT,
    email      TEXT,
    tier       TEXT DEFAULT 'standard',
    notes      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE UNIQUE INDEX IF NOT EXISTS idx_clients_phone ON clients(phone);
`);

const records = JSON.parse(fs.readFileSync(JSON_PATH, 'utf8'));

const upsert = db.prepare(`
  INSERT INTO clients (name, phone, address, email, tier, notes)
  VALUES (@name, @phone, @address, @email, @tier, @notes)
  ON CONFLICT(phone) DO UPDATE SET
    name    = excluded.name,
    address = excluded.address,
    email   = excluded.email,
    tier    = excluded.tier,
    notes   = excluded.notes
`);

const upsertMany = db.transaction((rows) => {
  let inserted = 0, updated = 0;
  for (const row of rows) {
    const phone = (row.phone || '').replace(/\D/g, '');
    const info = upsert.run({ ...row, phone });
    if (info.changes === 1) info.lastInsertRowid ? inserted++ : updated++;
  }
  return { inserted, updated };
});

const { inserted, updated } = upsertMany(records);
console.log(`[seed_clients] Done. ${inserted} inserted, ${updated} updated. Total records in DB: ${db.prepare('SELECT COUNT(*) AS n FROM clients').get().n}`);

db.close();
