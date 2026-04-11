/**
 * scheduler.js — Schedule service calls via the calendar-agent API
 */

'use strict';

const CALENDAR_AGENT_URL = process.env.CALENDAR_AGENT_URL || 'http://calendar-agent:8094';

async function checkAvailability(dateStr, durationMin = 60) {
  const resp = await fetch(`${CALENDAR_AGENT_URL}/calendar/free-slots?date=${dateStr}&duration=${durationMin}`);
  if (!resp.ok) throw new Error(`Calendar agent error: ${resp.status}`);
  return resp.json();
}

async function scheduleServiceCall({ clientName, address, issue, dateTimeISO, durationMin = 60 }) {
  const endTime = new Date(new Date(dateTimeISO).getTime() + durationMin * 60000).toISOString();

  const resp = await fetch(`${CALENDAR_AGENT_URL}/calendar/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: `Service Call: ${clientName}`,
      start: dateTimeISO,
      end: endTime,
      notes: `Client: ${clientName}\nAddress: ${address}\nIssue: ${issue}\nScheduled by: Bob (voice receptionist)`,
    }),
  });

  if (!resp.ok) throw new Error(`Schedule error: ${resp.status}`);
  const result = await resp.json();

  // Publish to Redis for cortex and notifications
  try {
    const redis = require('redis');
    const client = redis.createClient({ url: process.env.REDIS_URL || 'redis://redis:6379' });
    await client.connect();
    await client.publish('notifications:calendar', JSON.stringify({
      type: 'service_call_scheduled',
      client: clientName,
      address,
      issue,
      datetime: dateTimeISO,
      source: 'voice_receptionist',
    }));
    await client.disconnect();
  } catch (e) {
    console.warn('[scheduler] Redis publish failed:', e.message);
  }

  return {
    success: true,
    message: `Service call scheduled for ${clientName} at ${new Date(dateTimeISO).toLocaleString('en-US', { timeZone: 'America/Denver' })}`,
    event: result,
  };
}

module.exports = { checkAvailability, scheduleServiceCall };
