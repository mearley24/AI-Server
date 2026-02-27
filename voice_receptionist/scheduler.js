/**
 * scheduler.js — Google Calendar service-call scheduling
 *
 * Exposes a single async function: scheduleServiceCall(details)
 * that creates a Calendar event and returns the event link.
 *
 * Auth: Service-account JSON key (path from GOOGLE_SERVICE_ACCOUNT_KEY env var).
 * The service account must be granted "Make changes to events" on the target calendar.
 */

'use strict';

require('dotenv').config();
const { google } = require('googleapis');
const path = require('path');

const KEY_PATH = process.env.GOOGLE_SERVICE_ACCOUNT_KEY ||
  path.join(__dirname, 'config', 'google-service-account.json');
const CALENDAR_ID = process.env.GOOGLE_CALENDAR_ID || 'primary';

// Lazy-init auth client
let authClient;
async function getAuthClient() {
  if (!authClient) {
    const auth = new google.auth.GoogleAuth({
      keyFile: KEY_PATH,
      scopes: ['https://www.googleapis.com/auth/calendar'],
    });
    authClient = await auth.getClient();
  }
  return authClient;
}

/**
 * Schedule a service call on Google Calendar.
 *
 * @param {object} details
 * @param {string}   details.clientName   — e.g. "The Andersons"
 * @param {string}   details.address      — service location
 * @param {string}   details.issue        — brief description
 * @param {string}   details.dateTimeISO  — ISO 8601 start time, e.g. "2025-07-15T09:00:00-06:00"
 * @param {number}   [details.durationMin=120] — event length in minutes
 * @param {string}   [details.techName]   — assigned technician (optional)
 * @returns {Promise<{eventId:string, eventLink:string, startTime:string}>}
 */
async function scheduleServiceCall(details) {
  const {
    clientName,
    address,
    issue,
    dateTimeISO,
    durationMin = 120,
    techName,
  } = details;

  const startDt = new Date(dateTimeISO);
  const endDt   = new Date(startDt.getTime() + durationMin * 60_000);

  const description = [
    `Client: ${clientName}`,
    `Address: ${address}`,
    `Issue: ${issue}`,
    techName ? `Technician: ${techName}` : '',
    '',
    'Scheduled by Bob the Conductor (AI receptionist)',
  ].filter(Boolean).join('\n');

  const auth  = await getAuthClient();
  const cal   = google.calendar({ version: 'v3', auth });

  const event = await cal.events.insert({
    calendarId: CALENDAR_ID,
    requestBody: {
      summary:     `Service Call — ${clientName}`,
      description,
      location:    address,
      start:  { dateTime: startDt.toISOString() },
      end:    { dateTime: endDt.toISOString() },
      colorId: '6', // tangerine
    },
  });

  return {
    eventId:   event.data.id,
    eventLink: event.data.htmlLink,
    startTime: startDt.toLocaleString('en-US', { timeZone: 'America/Denver' }),
  };
}

module.exports = { scheduleServiceCall };
