/**
 * client_lookup.js — Find Symphony client records
 *
 * On first use the module reads data/clients.json and imports it into
 * a local SQLite database (same DB used by call_logger).
 *
 * Lookup strategies (in priority order):
 *   1. Exact phone-number match (normalised to E.164 digits only)
 *   2. Case-insensitive name LIKE match
 *   3. Address LIKE match
 */

'use strict';

const Database = require('better-sqlite3');
const path = require('path');
const fs = require('fs');

const DB_PATH = process.env.DB_PATH || path.join(__dirname, 'data', 'bob.db');

let db;

function getDb() {
  if (!db) {
    db = new Database(DB_PATH);
    db.pragma('journal_mode = WAL');
    db.exec(`
      CREATE TABLE IF NOT EXISTS clients (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        name         TEXT NOT NULL,
        phone        TEXT,           -- normalised E.164 digits
        address      TEXT,
        email        TEXT,
        tier         TEXT DEFAULT 'standard',  -- 'standard'|'premium'|'enterprise'
        notes        TEXT,
        created_at   TEXT NOT NULL DEFAULT (datetime('now'))
      );
      CREATE INDEX IF NOT EXISTS idx_clients_phone ON clients(phone);
    `);
  }
  return db;
}

/**
 * Normalise a phone number to digits only (strips +, spaces, dashes, parens).
 */
function normalisePhone(raw) {
  return (raw || '').replace(/\D/g, '');
}

/**
 * Import clients.json into SQLite if the table is empty.
 */
function maybeImportClients() {
  const count = getDb().prepare('SELECT COUNT(*) AS n FROM clients').get().n;
  if (count > 0) return;

  const jsonPath = path.join(__dirname, 'data', 'clients.json');
  if (!fs.existsSync(jsonPath)) return;

  const records = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
  const insert = getDb().prepare(`
    INSERT INTO clients (name, phone, address, email, tier, notes)
    VALUES (@name, @phone, @address, @email, @tier, @notes)
  `);
  const insertMany = getDb().transaction((rows) => {
    for (const row of rows) {
      insert.run({
        name:    row.name,
        phone:   normalisePhone(row.phone),
        address: row.address || null,
        email:   row.email   || null,
        tier:    row.tier    || 'standard',
        notes:   row.notes   || null,
      });
    }
  });
  insertMany(records);
  console.log(`[client_lookup] Imported ${records.length} clients from JSON.`);
}

// Seed on module load
maybeImportClients();

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Look up a client by phone number.
 * @param {string} rawPhone — any format
 * @returns {object|null}
 */
function findByPhone(rawPhone) {
  const digits = normalisePhone(rawPhone);
  if (!digits) return null;
  // Try full match, then last-10
  return (
    getDb().prepare('SELECT * FROM clients WHERE phone = ? LIMIT 1').get(digits) ||
    getDb().prepare('SELECT * FROM clients WHERE phone LIKE ? LIMIT 1').get(`%${digits.slice(-10)}`)
  );
}

/**
 * Look up a client by name (partial, case-insensitive).
 * @param {string} nameQuery
 * @returns {object[]}
 */
function findByName(nameQuery) {
  return getDb()
    .prepare(`SELECT * FROM clients WHERE name LIKE ? LIMIT 5`)
    .all(`%${nameQuery}%`);
}

/**
 * Look up a client by address fragment.
 */
function findByAddress(addrQuery) {
  return getDb()
    .prepare(`SELECT * FROM clients WHERE address LIKE ? LIMIT 5`)
    .all(`%${addrQuery}%`);
}

/**
 * Get a client by primary key.
 */
function getById(id) {
  return getDb().prepare('SELECT * FROM clients WHERE id = ?').get(id);
}

module.exports = { findByPhone, findByName, findByAddress, getById };
