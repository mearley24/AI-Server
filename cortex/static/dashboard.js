'use strict';
(() => {
  const REFRESH_MS  = 60_000;
  const XI_PG_SIZE  = 50;

  // ── Helpers ──────────────────────────────────────────────────────────────

  const $ = (id) => document.getElementById(id);
  const fmtNum = (n, d = 2) =>
    (n == null || isNaN(n)) ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  const fmtUsd = (n) => (n == null || isNaN(n)) ? '—' : '$' + fmtNum(n, 2);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
    (c) => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
  const unavail = (msg = 'unavailable') => `<div class="unavailable">${esc(msg)}</div>`;

  const timeAgo = (iso) => {
    if (!iso) return '';
    const t = typeof iso === 'number' ? iso * 1000 : new Date(iso).getTime();
    if (isNaN(t)) return '';
    const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (s < 60)    return `${s}s ago`;
    if (s < 3600)  return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  };

  const fmtTs = (ts) => {
    if (!ts) return '';
    const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
    if (isNaN(d)) return String(ts).slice(0, 10);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' +
           d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  };

  // ── Freshness system ──────────────────────────────────────────────────────

  const _FRESH_ACTIVE_SECS = 3_600;          // < 1 h  → LIVE
  const _FRESH_RECENT_SECS = 86_400;         // < 24 h → RECENT
  const _FRESH_STALE_SECS  = 7 * 86_400;    // < 7 d  → STALE (else ARCHIVE)

  // Age of a timestamp in seconds (ISO string or unix seconds int)
  function ageSeconds(ts) {
    if (ts == null || ts === '') return Infinity;
    const t = typeof ts === 'number' ? ts * 1000 : new Date(ts).getTime();
    return isNaN(t) ? Infinity : Math.max(0, (Date.now() - t) / 1000);
  }

  // 'active' | 'recent' | 'stale' | 'archive'
  function freshnessTier(ts) {
    const s = ageSeconds(ts);
    if (s < _FRESH_ACTIVE_SECS) return 'active';
    if (s < _FRESH_RECENT_SECS) return 'recent';
    if (s < _FRESH_STALE_SECS)  return 'stale';
    return 'archive';
  }

  // Inline card-badge for a freshness tier
  function freshnessTag(ts) {
    const tier  = freshnessTier(ts);
    const cls   = { active: 'badge-live', recent: 'badge-stale', stale: 'badge-debug', archive: 'badge-debug' }[tier];
    const label = { active: 'LIVE', recent: 'RECENT', stale: 'STALE', archive: 'ARCHIVE' }[tier];
    return `<span class="card-badge ${cls}" style="font-size:8px;padding:0 4px;vertical-align:middle;">${label}</span>`;
  }

  // Consistent "nothing to show" empty state (green = system healthy, not broken)
  function emptyState(msg = 'No active items — system is clean') {
    return `<div style="color:var(--green);font-size:12px;padding:4px 0;">${esc(msg)}</div>`;
  }

  // Global debug mode — disables all freshness pruning.
  // Seeded from URL (?debug=1) immediately; overwritten by /api/dashboard/config on first refresh.
  let _debugMode = /[?&]debug=1/.test(window.location.search);

  async function fetchJson(url) {
    try {
      const r = await fetch(url, { cache: 'no-store' });
      return r.ok ? r.json() : null;
    } catch { return null; }
  }

  async function postJson(url, body) {
    try {
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
      });
      return r.ok ? r.json() : { ok: false, error: r.statusText };
    } catch (e) { return { ok: false, error: String(e) }; }
  }

  // ── Clock ─────────────────────────────────────────────────────────────────

  function tickClock() {
    try {
      $('clock').textContent = new Date().toLocaleString('en-US', {
        timeZone: 'America/Denver',
        hour: 'numeric', minute: '2-digit', hour12: true,
        month: 'short', day: 'numeric',
      }) + ' MT';
    } catch { $('clock').textContent = new Date().toLocaleString(); }
  }

  // ── Tab navigation ────────────────────────────────────────────────────────

  let _xiLoaded = false;
  let _trLoaded = false;
  let _symLoaded = false;
  let _siLoaded = false;
  let _riLoaded = false;
  let _markupCheckInterval = null;

  window.switchTab = function switchTab(name) {
    document.querySelectorAll('.tab-panel').forEach((p) => p.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
    const panel = $('tab-' + name);
    const btn   = document.querySelector(`.tab-btn[data-tab="${name}"]`);
    if (panel) panel.classList.add('active');
    if (btn)   btn.classList.add('active');
    window.location.hash = name === 'overview' ? '' : name;
    if (['overview', 'xintake', 'symphony', 'autonomy'].includes(name)) {
      loadToolAccess(name);
    }
    if (name === 'xintake'          && !_xiLoaded) { _xiLoaded = true; loadXIntake(); loadFollowUps(); }
    if (name === 'transcripts'      && !_trLoaded) { _trLoaded = true; loadTranscripts(); }
    if (name === 'autonomy'         && !_autonomyLoaded) { loadAutonomy(); }
    if (name === 'self-improvement' && !_siLoaded) { _siLoaded = true; loadSelfImprovement(); }
    if (name === 'reply-inbox'      && !_riLoaded) { _riLoaded = true; loadReplyInbox(); }
    if (name === 'symphony') {
      if (!_symLoaded) { _symLoaded = true; loadSymphonyOps(); }
      checkMarkupHealth();
      checkBlueBubblesHealth();
      if (!_markupCheckInterval) {
        _markupCheckInterval = setInterval(() => {
          if ($('tab-symphony') && $('tab-symphony').classList.contains('active')) {
            checkMarkupHealth();
            checkBlueBubblesHealth();
            loadVoiceReceptionist();
          }
        }, 30000);
      }
    }
  };

  document.querySelectorAll('.tab-btn').forEach((b) =>
    b.addEventListener('click', () => switchTab(b.dataset.tab)));

  const _hashTab = window.location.hash.replace('#', '');
  if (['xintake', 'transcripts', 'symphony', 'autonomy', 'self-improvement', 'reply-inbox'].includes(_hashTab))
    setTimeout(() => switchTab(_hashTab), 50);

  // ── Tool access registry ──────────────────────────────────────────────────

  const _toolAccessLoaded = Object.create(null);

  function renderToolAccess(tools) {
    if (!Array.isArray(tools) || tools.length === 0) {
      return unavail('no tools registered for this tab');
    }
    return tools.map((t) => {
      const port = (t.port != null) ? (':' + esc(t.port)) : '';
      const cat = t.category ? esc(t.category) : '';
      const meta = [cat, port].filter(Boolean).join(' · ');
      const localLink = t.local_url
        ? `<a class="tlink" href="${esc(t.local_url)}" target="_blank" rel="noopener" title="local on Bob">local ↗</a>`
        : '';
      const tsLink = t.tailscale_url
        ? `<a class="tlink ts" href="${esc(t.tailscale_url)}" target="_blank" rel="noopener" title="Tailscale IP ${esc(t.tailscale_url)}">tailscale ↗</a>`
        : (t.status === 'unknown'
            ? `<span class="tlink unknown" title="port not documented in PORTS.md">tailscale —</span>`
            : '');
      const fqdnLink = t.tailscale_fqdn_url
        ? `<a class="tlink ts" href="${esc(t.tailscale_fqdn_url)}" target="_blank" rel="noopener" title="Tailscale MagicDNS ${esc(t.tailscale_fqdn_url)}">magic ↗</a>`
        : '';
      const note = t.notes ? `<div class="tnote">${esc(t.notes)}</div>` : '';
      return `<div class="tool-row" data-tool="${esc(t.name)}">
        <span class="tname">${esc(t.name)}</span>
        <span class="tmeta">${meta}</span>
        <span class="tlinks">${localLink}${tsLink}${fqdnLink}</span>
        ${note}
      </div>`;
    }).join('');
  }

  async function loadToolAccess(tab) {
    const host = $('tool-access-' + tab);
    if (!host) return;
    if (_toolAccessLoaded[tab]) return;
    const data = await fetchJson('/api/tools?tab=' + encodeURIComponent(tab));
    if (!data) { host.innerHTML = unavail('registry unavailable'); return; }
    host.innerHTML = renderToolAccess(data.tools || []);
    _toolAccessLoaded[tab] = true;
  }

  window.loadToolAccess = loadToolAccess;

  // ── Badge helpers ─────────────────────────────────────────────────────────

  function statusClass(s) {
    return { pending: 's-pending', approved: 's-approved', auto_approved: 's-auto_approved',
             rejected: 's-rejected', auto_rejected: 's-auto_rejected', error: 's-error' }[s] || 's-info';
  }
  function typeClass(t) {
    return { build: 't-build', alpha: 't-alpha', stat: 't-stat',
             tool: 't-tool', warn: 't-warn', info: 't-info' }[t] || 't-info';
  }
  function relClass(n) { return n >= 70 ? 'rel-high' : n >= 40 ? 'rel-mid' : 'rel-low'; }

  // Strip emoji-prefix lines, "Action:", "Relevance:" from LLM summary blocks
  function extractSummary(raw) {
    if (!raw) return '';
    return (raw.split('\n').filter((l) => {
      const t = l.trim();
      if (!t || /^Action:/i.test(t) || /^Relevance:/i.test(t)) return false;
      if (/^@\w/.test(t)) return false;
      if (/^\p{Emoji}/u.test(t)) return false;
      return true;
    }).slice(0, 3).join(' ')).slice(0, 220);
  }

  // ── Overview renderers ────────────────────────────────────────────────────

  function renderServices(data) {
    const host = $('services'), sum = $('services-summary');
    if (!data || !data.services) { host.innerHTML = unavail(); return; }
    host.innerHTML = data.services.map((s) => {
      const st = s.status === 'healthy' ? 'healthy' : s.status === 'degraded' ? 'degraded' : 'down';
      return `<div class="svc-item" title="${esc(s.name)} — ${esc(s.status)}">
        <span class="dot ${st}"></span>
        <span class="name">${esc(s.name)}</span>
        <span class="port">${s.port != null ? ':' + esc(s.port) : 'internal'}</span>
      </div>`;
    }).join('');
    const core = data.healthy_core != null ? `${data.healthy_core}/${data.total_core} core` : '';
    const opt  = data.optional_total ? `${data.optional_healthy}/${data.optional_total} optional` : '';
    sum.textContent = [core, opt].filter(Boolean).join(' · ');
  }

  const _RISK_COLOR = { high: 'var(--red)', medium: 'var(--yellow)', low: 'var(--green)', unknown: 'var(--muted)' };

  function _wdCopyCmd(cmd) {
    navigator.clipboard.writeText(cmd).catch(() => {});
  }
  window._wdCopyCmd = _wdCopyCmd;

  function _wdDegradedCard(s) {
    const riskColor = _RISK_COLOR[s.recovery_risk] || 'var(--muted)';
    const riskLabel = (s.recovery_risk || 'unknown').toUpperCase();

    const impactsHtml = (s.downstream_impacts || []).length
      ? `<div class="small" style="margin-top:5px;color:var(--muted)">Affects: ${esc((s.downstream_impacts || []).join(', '))}</div>`
      : '';

    const impactSummary = s.impact_summary
      ? `<div class="small" style="margin-top:3px;color:var(--yellow)">${esc(s.impact_summary)}</div>`
      : '';

    const checkHtml = (s.suggested_checks || []).length
      ? `<div style="margin-top:8px">
          <div class="small" style="color:var(--muted);margin-bottom:3px">Check:</div>
          <div class="wd-cmd-row">
            <code class="wd-cmd">${esc(s.suggested_checks[0])}</code>
            <button class="wd-copy-btn" onclick="_wdCopyCmd(${JSON.stringify(s.suggested_checks[0])})" title="Copy">&#x2398;</button>
          </div>
        </div>`
      : '';

    const recoveryHtml = s.suggested_recovery
      ? `<div style="margin-top:6px">
          <div class="small" style="color:var(--muted);margin-bottom:3px">
            Recovery <span style="color:${riskColor};font-weight:600">[${riskLabel} RISK]</span>:
          </div>
          <div class="wd-cmd-row">
            <code class="wd-cmd">${esc(s.suggested_recovery)}</code>
            <button class="wd-copy-btn" onclick="_wdCopyCmd(${JSON.stringify(s.suggested_recovery)})" title="Copy">&#x2398;</button>
          </div>
          ${s.recovery_notes ? `<div class="small" style="color:var(--muted);margin-top:3px">${esc(s.recovery_notes)}</div>` : ''}
        </div>`
      : '';

    return `<div class="wd-degraded-card">
      <div style="display:flex;align-items:center;gap:6px">
        <span class="dot degraded"></span>
        <strong>${esc(s.name)}</strong>
        <span class="small" style="color:var(--muted)">${esc(s.details)}</span>
      </div>
      ${impactSummary}${impactsHtml}${checkHtml}${recoveryHtml}
    </div>`;
  }

  function renderWatchdog(data) {
    const host    = $('watchdog-overview');
    const banner  = $('wd-header-alert');
    const bannerT = $('wd-alert-text');

    if (!data || data.status === 'error') {
      host.innerHTML = unavail();
      banner.classList.add('hidden');
      return;
    }

    const degraded = data.degraded_count || 0;
    const services = data.services || [];
    const wdAge    = data.updated_at;
    const wdStale  = ageSeconds(wdAge) > _FRESH_ACTIVE_SECS && !_debugMode;
    const updatedAt = wdAge ? ' · updated ' + timeAgo(wdAge) : '';
    const staleBadge = wdStale ? freshnessTag(wdAge) : '';

    // Header banner — show degraded service names (always, even if watchdog data is stale)
    if (degraded > 0) {
      const degradedSvcs = services.filter(s => s.state === 'degraded');
      const names = degradedSvcs.map(s => s.name).join(', ');
      bannerT.textContent = `⚠ ${degraded} degraded: ${names}`;
      banner.classList.remove('hidden');
    } else {
      banner.classList.add('hidden');
    }

    // Overview card
    if (!services.length) {
      const warn = data.warning ? `<div class="small" style="color:var(--muted);margin-top:4px">${esc(data.warning)}</div>` : '';
      host.innerHTML = `<div class="small" style="color:var(--green)">&#10003; all clear${updatedAt}</div>${staleBadge}${warn}`;
      return;
    }

    const degradedSvcs = services.filter(s => s.state === 'degraded');
    // In normal mode: hide resolved (ok) services whose state has been ok for >1h
    const okSvcs = services.filter(s => s.state === 'ok');

    if (degraded === 0) {
      host.innerHTML = `<div class="small" style="color:var(--green)">&#10003; all clear &mdash; ${services.length} service${services.length !== 1 ? 's' : ''} monitored${updatedAt} ${staleBadge}</div>`;
      return;
    }

    const cards = degradedSvcs.map(_wdDegradedCard).join('');
    const okLine = okSvcs.length
      ? `<div class="small" style="color:var(--muted);margin-top:8px">${okSvcs.length} service${okSvcs.length !== 1 ? 's' : ''} ok${updatedAt} ${staleBadge}</div>`
      : '';

    host.innerHTML = cards + okLine;
  }

  function renderEmails(data) {
    const host = $('emails');
    if (!data || data.error || (!data.emails && data.unread_count == null)) { host.innerHTML = unavail(); return; }
    const list    = (data.emails || []).slice(0, 5);
    const ageStr  = data.as_of ? 'updated ' + timeAgo(data.as_of) : '';
    if (!list.length) {
      host.innerHTML = `<div class="stat-big">${esc(data.unread_count ?? 0)}</div>
        <div class="stat-label">unread (7d)</div>
        ${ageStr ? `<div class="small" style="margin-top:4px">${esc(ageStr)}</div>` : ''}`;
      return;
    }
    host.innerHTML = `<div class="stat-big">${esc(data.unread_count ?? 0)}</div>
      <div class="stat-label">unread (7d)</div>
      <ul style="margin-top:8px">
        ${list.map((e) => `<li title="${esc(e.sender||'')}">${esc((e.subject||e.title||'(no subject)').slice(0,72))}</li>`).join('')}
      </ul>
      ${ageStr ? `<div class="small" style="margin-top:4px">${esc(ageStr)}</div>` : ''}`;
  }

  function renderCalendar(data) {
    const host = $('calendar');
    if (!data || !data.events) { host.innerHTML = unavail(); return; }
    const list = (data.events || []).slice(0, 5);
    if (!list.length) { host.innerHTML = `<div class="small">no upcoming events</div>`; return; }
    host.innerHTML = `<ul>${list.map((e) => {
      const when  = e.start_display || e.start || e.time || e.date || '';
      const title = e.title || e.summary || '(no title)';
      const recur = e.is_recurring ? ' <span style="font-size:10px;color:var(--gold-dim)" title="recurring">&#8635;</span>' : '';
      const desc  = e.description
        ? `<span class="small" style="display:block;color:var(--muted);margin-top:1px">${esc(e.description.slice(0,60))}</span>` : '';
      return `<li><strong>${esc(title)}</strong>${recur}<br><span class="small">${esc(when)||'&nbsp;'}</span>${desc}</li>`;
    }).join('')}</ul>`;
  }

  function renderFollowups(data) {
    const host = $('followups');
    if (!data || data.error) { host.innerHTML = unavail(); return; }
    const total   = data.total ?? 0;
    const overdue = data.overdue_count ?? 0;
    const next    = (data.followups || [])[0];
    const nextLbl = next ? `${esc(next.client_name||next.client_email||'—')} — ${esc(next.last_client_subject||'')}` : 'none';
    const ageStr  = data.as_of ? 'updated ' + timeAgo(data.as_of) : '';
    host.innerHTML = `
      <div class="stat-row">
        <div><div class="stat-big">${esc(total)}</div><div class="stat-label">active (30d)</div></div>
        <div><div class="stat-big" style="color:${overdue>0?'var(--red)':'var(--muted)'}">${esc(overdue)}</div><div class="stat-label">overdue</div></div>
      </div>
      <div class="small" style="margin-top:8px">next: ${nextLbl.slice(0,80)}</div>
      ${ageStr ? `<div class="small" style="margin-top:4px">${esc(ageStr)}</div>` : ''}`;
  }

  // Render the Calls / Voice Receptionist card. The upstream service
  // (/api/symphony/voice-receptionist) returns a stable shape even when
  // offline, plus a `planned` block describing the future contract so we
  // render an honest empty state instead of fake activity.
  function renderCalls(data) {
    const host = $('calls');
    if (!host) return;
    if (!data) { host.innerHTML = unavail(); return; }
    const svc = data.service || {};
    const dot = svc.status === 'online' ? 'healthy'
              : svc.status === 'degraded' ? 'degraded'
              : svc.status === 'offline' ? 'down' : 'down';
    const recent = Array.isArray(data.recent_calls) ? data.recent_calls : [];
    const missed = Array.isArray(data.missed_calls) ? data.missed_calls : [];
    const vm     = Array.isArray(data.voicemails) ? data.voicemails : [];
    const planned = data.planned || {};
    const fields  = (planned.fields || []).slice(0, 6).join(', ');
    const actions = (planned.actions || []).slice(0, 5).join(' · ');
    const empty = !recent.length && !missed.length && !vm.length;
    host.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
        <span class="dot ${dot}"></span>
        <span class="small">${esc(svc.status || 'unknown')}</span>
        <span class="small" style="color:var(--muted);margin-left:auto">:8093</span>
      </div>
      <div class="stat-row">
        <div><div class="stat-big">${esc(recent.length)}</div><div class="stat-label">recent (24h)</div></div>
        <div><div class="stat-big" style="color:${missed.length>0?'var(--red)':'var(--muted)'}">${esc(missed.length)}</div><div class="stat-label">missed</div></div>
        <div><div class="stat-big">${esc(vm.length)}</div><div class="stat-label">voicemail</div></div>
      </div>
      ${empty ? `<div class="small" style="margin-top:8px;color:var(--muted)">
        Cortex call ingestion not yet wired. Planned: ${esc(fields || 'caller, transcript, matched client/project, suggested follow-up')}.
        Actions: ${esc(actions || 'text · email · create intake · escalate')}.
      </div>` : ''}
    `;
  }

  function renderCallsSymphony(data) {
    const host = $('calls-symphony');
    if (!host) return;
    if (!data) { host.innerHTML = unavail(); return; }
    const svc = data.service || {};
    const dot = svc.status === 'online' ? 'healthy'
              : svc.status === 'degraded' ? 'degraded'
              : svc.status === 'offline' ? 'down' : 'down';
    const planned = data.planned || {};
    const fields  = planned.fields || [];
    const actions = planned.actions || [];
    const channel = planned.redis_channel || '';
    const ingestion = planned.ingestion || '';
    host.innerHTML = `
      <div style="display:flex;gap:24px;align-items:center;flex-wrap:wrap;margin-bottom:10px;">
        <div><div class="small muted">STATUS</div><div><span class="dot ${dot}"></span> ${esc(svc.status || 'unknown')}</div></div>
        <div><div class="small muted">URL</div><div class="mono small">${esc(svc.url || '')}</div></div>
        <div><div class="small muted">CHECKED</div><div class="small">${esc(timeAgo(svc.checked_at) || '—')}</div></div>
        ${channel ? `<div><div class="small muted">REDIS CHANNEL</div><div class="mono small">${esc(channel)}</div></div>` : ''}
      </div>
      <div class="small" style="color:var(--muted);margin-bottom:8px">
        ${esc(ingestion)}
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
        <div>
          <div class="small muted" style="margin-bottom:4px">PLANNED FIELDS</div>
          <ul class="small" style="margin:0;padding-left:16px;color:var(--muted)">
            ${fields.map((f) => `<li>${esc(f)}</li>`).join('')}
          </ul>
        </div>
        <div>
          <div class="small muted" style="margin-bottom:4px">PLANNED ACTIONS</div>
          <ul class="small" style="margin:0;padding-left:16px;color:var(--muted)">
            ${actions.map((a) => `<li>${esc(a)}</li>`).join('')}
          </ul>
        </div>
      </div>
      <div class="small" style="margin-top:10px;color:var(--muted)">
        No live recent-calls feed yet — the receptionist's SQLite call log + OpenAI transcripts
        will be mirrored into Cortex by a follow-up worker. Existing follow-up signals already flow
        through Redis <code>ops:voice_followup</code> → Linear (<code>operations/linear_ops.py</code>).
      </div>
    `;
  }

  function renderWallet(data) {
    const host = $('wallet');
    if (!data || data.error) { host.innerHTML = unavail(data?.error || 'unavailable'); return; }
    const usdc    = Number(data.usdc_balance || 0);
    const active  = Number(data.active_value || data.position_value || 0);
    const snapAge = data.snapshot_age ? 'updated ' + timeAgo(data.snapshot_age) : 'live';
    const ftag    = data.snapshot_age ? freshnessTag(data.snapshot_age) : '';
    host.innerHTML = `
      <div class="stat-big">${fmtUsd(usdc + active)}</div>
      <div class="stat-label">account value</div>
      <div class="stat-row" style="margin-top:8px">
        <div><div class="small">USDC</div><div class="mono">${fmtUsd(usdc)}</div></div>
        <div><div class="small">Open</div><div class="mono">${fmtUsd(active)}</div></div>
      </div>
      <div class="small" style="margin-top:6px">${esc(snapAge)} ${ftag}</div>`;
  }

  function renderPositions(data) {
    const host = $('positions');
    if (!data) { host.innerHTML = unavail(); return; }
    const positions = Array.isArray(data) ? data : (data.positions || []);
    if (!positions.length) { host.innerHTML = `<div class="small">no open positions</div>`; return; }
    const exposure = positions.reduce((s, p) => s + Number(p.currentValue || p.current_value || 0), 0);
    host.innerHTML = `
      <div class="stat-row">
        <div><div class="stat-big">${positions.length}</div><div class="stat-label">open</div></div>
        <div><div class="stat-big mono">${fmtUsd(exposure)}</div><div class="stat-label">exposure</div></div>
      </div>
      <ul style="margin-top:8px">
        ${positions.slice(0,5).map((p) => `<li>${esc((p.title||p.market||'').slice(0,60))} <span class="small mono">${fmtUsd(p.currentValue||p.current_value||0)}</span></li>`).join('')}
      </ul>`;
  }

  function renderPnl(wallet, pnlSummary) {
    const host = $('pnl');
    if (!wallet || wallet.error) { host.innerHTML = unavail(); return; }
    const daily   = Number(wallet.daily_pnl || 0);
    const allTime = pnlSummary && !pnlSummary.error ? Number(pnlSummary.realized_pnl || 0) : null;
    const cls  = (n) => n > 0 ? 'pnl-positive' : n < 0 ? 'pnl-negative' : 'pnl-neutral';
    const sign = (n) => n >= 0 ? '+' : '';
    const allTimeHtml = allTime !== null
      ? `<div><div class="stat-big ${cls(allTime)}">${sign(allTime)}${fmtUsd(allTime)}</div><div class="stat-label">all-time realized</div></div>`
      : `<div><div class="stat-big pnl-neutral">—</div><div class="stat-label">all-time realized</div></div>`;
    host.innerHTML = `
      <div class="stat-row">
        <div><div class="stat-big ${cls(daily)}">${sign(daily)}${fmtUsd(daily)}</div><div class="stat-label">today</div></div>
        ${allTimeHtml}
      </div>`;
  }

  function renderActivity(data) {
    const host = $('activity');
    if (!Array.isArray(data) || !data.length) {
      host.innerHTML = emptyState('No recent activity — system is quiet');
      return;
    }
    const items = data.slice(0, 10).map((e) => {
      const p    = e.payload || e;
      const t    = p.type || e.channel || 'event';
      const when = e.ts || e.timestamp || p.ts || p.timestamp || '';
      const msg  = p.message || p.msg || e.message || '';
      const ftag = when ? freshnessTag(when) : '';
      return `<li><span class="mono small">${esc(t)}</span> ${esc((msg||'').slice(0,50))} <span class="small">${esc(timeAgo(when))}</span>${ftag}</li>`;
    });
    host.innerHTML = `<ul>${items.join('')}</ul>`;
  }

  function renderRedeemer(data) {
    const host = $('redeemer');
    if (!data || data.error) { host.innerHTML = unavail(data?.error || 'unavailable'); return; }
    const dotCls   = data.running ? 'healthy' : 'down';
    const summ     = data.last_cycle_summary || {};
    const redeemed = summ.redeemed ?? 0;
    const pending  = summ.pending  ?? 0;
    const status   = summ.status || (redeemed > 0 ? 'redeemed' : 'idle');
    const recovered = summ.recovered != null ? fmtUsd(summ.recovered) : null;
    host.innerHTML = `
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px">
        <span class="dot ${dotCls}" style="display:inline-block"></span>
        <span class="small">${data.running ? 'running' : 'stopped'}</span>
        <span class="small" style="margin-left:auto">${data.check_interval ? Math.round(data.check_interval/60)+'min cycle' : ''}</span>
      </div>
      <div class="stat-row">
        <div><div class="stat-big">${esc(data.redeemed_conditions||0)}</div><div class="stat-label">redeemed total</div></div>
        <div><div class="stat-big" style="color:${pending>0?'var(--yellow)':'var(--muted)'}">${esc(pending)}</div><div class="stat-label">pending</div></div>
      </div>
      <div class="small" style="margin-top:8px">last run: ${esc(data.last_cycle_at ? timeAgo(data.last_cycle_at) : 'never')} — ${esc(status)}${recovered&&redeemed>0?' — recovered '+recovered:''}</div>
      <div class="small" style="margin-top:4px">gas (POL): ${Number(data.matic_balance||0).toFixed(2)}</div>`;
  }

  function renderPolyExposure(data) {
    const host = $('polyexposure');
    if (!data || data.error) { host.innerHTML = unavail(data?.error || 'unavailable'); return; }
    const cls  = (n) => n > 0 ? 'pnl-positive' : n < 0 ? 'pnl-negative' : 'pnl-neutral';
    const sign = (n) => n > 0 ? '+' : '';
    const pnl  = Number(data.unrealized_pnl || 0);
    const val  = Number(data.current_value  || 0);
    const cost = Number(data.cost_basis     || 0);
    const winners = (data.top_winners || []).slice(0, 3);
    const losers  = (data.top_losers  || []).slice(0, 3);
    const age = data.fetched_at ? timeAgo(data.fetched_at) : '';

    const posRow = (p, isWinner) => {
      const pnlCls = isWinner ? 'pnl-positive' : 'pnl-negative';
      const market = (p.market || '').slice(0, 48);
      return `<li style="display:flex;justify-content:space-between;gap:6px;margin-bottom:3px">
        <span class="small" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(market)}</span>
        <span class="small mono ${pnlCls}" style="white-space:nowrap">${sign(p.pnl)}${fmtUsd(p.pnl)}</span>
      </li>`;
    };

    host.innerHTML = `
      <div class="stat-row" style="margin-bottom:10px">
        <div>
          <div class="stat-big mono">${fmtUsd(val)}</div>
          <div class="stat-label">current value</div>
        </div>
        <div>
          <div class="stat-big mono ${cls(pnl)}">${sign(pnl)}${fmtUsd(pnl)}</div>
          <div class="stat-label">unrealized P&L</div>
        </div>
      </div>
      <div class="stat-row" style="margin-bottom:10px">
        <div><div class="small mono">${fmtUsd(cost)}</div><div class="stat-label">cost basis</div></div>
        <div><div class="small mono">${esc(data.position_count)}</div><div class="stat-label">positions</div></div>
      </div>
      ${winners.length ? `
        <div class="small" style="color:var(--muted);margin-bottom:4px">top winners</div>
        <ul style="margin:0 0 8px;padding:0;list-style:none">${winners.map((p) => posRow(p, true)).join('')}</ul>
      ` : ''}
      ${losers.length ? `
        <div class="small" style="color:var(--muted);margin-bottom:4px">top losers</div>
        <ul style="margin:0 0 8px;padding:0;list-style:none">${losers.map((p) => posRow(p, false)).join('')}</ul>
      ` : ''}
      <div class="small" style="color:var(--muted);margin-top:4px">
        ${esc(data.wallet)} · ${esc(data.source)} · ${esc(age)}
      </div>`;
  }

  function renderMemory(stats, memories) {
    const host = $('memory');
    if (!stats && !memories) { host.innerHTML = unavail(); return; }
    const total  = (stats && (stats.total ?? stats.memories)) ?? 0;
    const recent = (memories || []).slice(0, 5);
    host.innerHTML = `
      <div class="stat-big">${esc(total)}</div>
      <div class="stat-label">memories total</div>
      <ul style="margin-top:8px">
        ${recent.map((m) => `<li>${esc((m.title||m.content||'').slice(0,70))}</li>`).join('')||'<li class="small">no recent memories</li>'}
      </ul>`;
  }

  function renderGoals(data) {
    const host = $('goals');
    if (!Array.isArray(data) || !data.length) { host.innerHTML = unavail('no active goals'); return; }
    host.innerHTML = data.slice(0, 4).map((g) => {
      const pct = Math.max(0, Math.min(100, Number(g.progress_pct ?? g.progress ?? 0)));
      const barCls = g.status === 'at_risk' ? 'red' : g.status === 'complete' ? 'green' : '';
      return `<div style="margin-bottom:10px">
        <div class="row" style="padding:0">
          <span>${esc((g.title||g.name||g.id||'goal').slice(0,60))}</span>
          <span class="small mono">${pct.toFixed(0)}%</span>
        </div>
        <div class="goal-bar ${barCls}"><div style="width:${pct}%"></div></div>
      </div>`;
    }).join('');
  }

  function renderDecisions(data) {
    const host = $('decisions'), card = $('decisions-card');
    if (!data) { host.innerHTML = unavail(); return; }

    const _dTs = (d) => d.created_at || d.updated_at || d.timestamp || d.date || null;

    const allJournal = data.journal || [];
    const allCortex  = data.cortex  || [];

    // In normal mode filter to RECENT (<24h); debug shows everything
    const journal = _debugMode ? allJournal : allJournal.filter((d) => ageSeconds(_dTs(d)) < _FRESH_RECENT_SECS);
    const cortex  = _debugMode ? allCortex  : allCortex.filter( (d) => ageSeconds(_dTs(d)) < _FRESH_RECENT_SECS);

    const jCnt    = journal.length;
    const pending = journal.filter((d) => (d.status||'').toLowerCase() === 'pending').length;
    if (card) { if (pending > 20) card.classList.add('alert'); else card.classList.remove('alert'); }

    if (!_debugMode && !jCnt && !cortex.length) {
      const total = allJournal.length + allCortex.length;
      host.innerHTML = emptyState(`No active decisions in the last 24h${total > 0 ? ` (${total} archived)` : ''}`) +
        `<div class="small" style="margin-top:6px;color:var(--muted)">Full history → <a href="#" onclick="switchTab('debug');return false;" style="color:var(--muted)">Debug tab</a></div>`;
      return;
    }

    const staleBanner = !_debugMode
      ? `<div class="small" style="margin-top:6px;color:var(--muted)">showing last 24h · <a href="#" onclick="switchTab('debug');return false;" style="color:var(--muted)">Debug tab for full history</a></div>`
      : `<div class="small" style="margin-top:6px;color:var(--yellow)">debug mode — showing all ${allJournal.length + allCortex.length} items</div>`;

    host.innerHTML = `
      <div class="stat-row">
        <div><div class="stat-big">${esc(jCnt)}</div><div class="stat-label">recent</div></div>
        <div><div class="stat-big" style="color:${pending>20?'var(--red)':'var(--text)'}">${esc(pending)}</div><div class="stat-label">pending</div></div>
      </div>
      <ul style="margin-top:8px">
        ${cortex.slice(0,5).map((d) => `<li>${esc((d.title||d.content||'').slice(0,70))} ${freshnessTag(_dTs(d))}</li>`).join('')||'<li class="small">no cortex decisions</li>'}
      </ul>
      ${staleBanner}`;
  }

  function renderDigest(data) {
    const host = $('digest');
    if (!data) { host.innerHTML = unavail(); return; }
    const s = data.summary || data.headline || data.digest || '';
    host.innerHTML = s
      ? `<div class="small" style="white-space:pre-wrap">${esc(String(s).slice(0,400))}</div>`
      : `<div class="small">no digest yet</div>`;
  }

  function renderMeetings(data) {
    // data: array from GET /api/meetings/recent ; [] means "pipeline idle or db not mounted"
    const host = $('meetings'), card = $('meetings-card');
    if (!Array.isArray(data) || !data.length) {
      host.innerHTML = emptyState('No recent meetings — pipeline idle');
      if (card) card.classList.remove('alert');
      return;
    }

    // In normal mode, hide rows older than 7 days (STALE threshold).
    // In-progress/pending rows are always shown regardless of age.
    const _isActive = (r) => ['transcribing', 'analyzing', 'pending', 'failed'].includes(r.status);
    const visible = _debugMode
      ? data
      : data.filter((r) => _isActive(r) || ageSeconds(r.source_date) < _FRESH_STALE_SECS);

    const today      = new Date().toISOString().slice(0, 10);
    const doneToday  = visible.filter((r) => r.status === 'done' && r.source_date === today).length;
    const processing = visible.filter((r) => _isActive(r) && r.status !== 'failed').length;
    const failed     = visible.filter((r) => r.status === 'failed').length;
    const archived   = data.length - visible.length;
    if (card) { if (failed > 0) card.classList.add('alert'); else card.classList.remove('alert'); }

    if (!_debugMode && !visible.length) {
      host.innerHTML = emptyState('No recent meetings in the last 7 days') +
        (archived > 0 ? `<div class="small" style="margin-top:4px;color:var(--muted)">${archived} archived</div>` : '');
      return;
    }

    const rows = visible.slice(0, 3).map((r) => {
      const clients = Array.isArray(r.clients) ? r.clients.slice(0, 2).join(', ') : '';
      const sm      = (r.summary || '').slice(0, 70);
      const dotCls  = r.status === 'done' ? 'healthy' : r.status === 'failed' ? 'down' : 'degraded';
      const ftag    = freshnessTag(r.source_date || r.created_at);
      return `<li style="padding:5px 0">
        <div style="display:flex;align-items:center;gap:6px">
          <span class="dot ${dotCls}"></span>
          <span class="small mono" style="color:var(--muted)">${esc(r.source_date||'')}</span>
          ${ftag}
          <span class="small" style="margin-left:auto;color:var(--muted)">${esc(r.status||'')}</span>
        </div>
        <div class="small" style="margin-top:2px;color:var(--text)">${esc(sm || r.original_name || '—')}</div>
        ${clients ? `<div class="small" style="color:var(--gold-dim)">clients: ${esc(clients)}</div>` : ''}
      </li>`;
    }).join('');

    host.innerHTML = `
      <div class="stat-row">
        <div><div class="stat-big" style="color:var(--green)">${doneToday}</div><div class="stat-label">done today</div></div>
        <div><div class="stat-big" style="color:${processing>0?'var(--yellow)':'var(--muted)'}">${processing}</div><div class="stat-label">in queue</div></div>
      </div>
      ${failed ? `<div class="small" style="color:var(--red);margin-top:4px">${failed} failed</div>` : ''}
      ${archived && !_debugMode ? `<div class="small" style="color:var(--muted);margin-top:2px">${archived} older meeting${archived!==1?'s':''} hidden (>7d) <span class="card-badge badge-debug">ARCHIVE</span></div>` : ''}
      <ul style="margin-top:8px">${rows}</ul>`;
  }

  function renderFooter(stats, wallet, emails, system) {
    const chunks = [];
    if (stats)  chunks.push(`<span><strong>${stats.total??0}</strong> memories</span>`);
    if (wallet) chunks.push(`<span><strong>${fmtUsd((wallet.usdc_balance||0)+(wallet.active_value||wallet.position_value||0))}</strong> AUM</span>`);
    if (emails) chunks.push(`<span><strong>${emails.unread_count??0}</strong> unread</span>`);
    if (system) {
      if (system.containers_total != null)
        chunks.push(`<span><strong>${system.containers_healthy??0}/${system.containers_total??0}</strong> svcs</span>`);
      if (system.memory_percent != null)
        chunks.push(`<span><strong>${system.memory_percent}%</strong> mem</span>`);
      if (system.disk_percent != null)
        chunks.push(`<span><strong>${system.disk_percent}%</strong> disk</span>`);
    }
    $('footer-stats').innerHTML = chunks.join('');
    if (system?.uptime_seconds != null)
      $('uptime').textContent = `uptime ${Math.floor(system.uptime_seconds/3600)}h`;
  }

  // ── Overview X Intake widget ──────────────────────────────────────────────

  window.xintakeAction = async function xintakeAction(id, action) {
    await fetch(`/api/x-intake/${id}/${action}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    }).catch(() => {});
    const [stats, queue] = await Promise.all([
      fetchJson('/api/x-intake/stats'),
      fetchJson('/api/x-intake/queue?status=pending&limit=5'),
    ]);
    renderXIntakeWidget(stats, queue);
  };

  function _updateNavBadge(pending) {
    const el = $('nav-xi-count');
    if (pending > 0) { el.textContent = pending; el.classList.remove('hidden'); }
    else el.classList.add('hidden');
  }

  function renderXIntakeWidget(stats, queue) {
    const host = $('xintake'), card = $('xintake-card');
    if (!stats && !queue) { host.innerHTML = unavail(); return; }
    const s = stats || {};
    const pending  = s.pending        || 0;
    const autoOk   = s.auto_approved  || 0;
    const rejected = (s.auto_rejected || 0) + (s.rejected || 0);
    const humanOk  = s.approved       || 0;
    const total    = s.total          || 0;
    _updateNavBadge(pending);
    if (pending > 0) card.classList.add('alert'); else card.classList.remove('alert');
    const items = ((queue?.items) || []).slice(0, 5);
    let html = `
      <div class="stat-row">
        <div><div class="stat-big" style="color:${pending>0?'var(--yellow)':'var(--muted)'}">${pending}</div><div class="stat-label">pending review</div></div>
        <div><div class="stat-big" style="color:var(--green)">${autoOk}</div><div class="stat-label">auto-approved</div></div>
      </div>
      <div class="small" style="margin-top:4px;margin-bottom:8px">${rejected} rejected &middot; ${humanOk} human &#10003; &middot; ${total} total (30d)</div>`;
    if (items.length) {
      html += '<ul style="margin-top:2px">';
      for (const item of items) {
        const rel     = item.relevance || 0;
        const author  = item.author || '?';
        const ptype   = item.post_type || 'info';
        const sumDisp = extractSummary(item.summary).slice(0, 90);
        const relCol  = rel >= 70 ? 'var(--green)' : rel >= 40 ? 'var(--yellow)' : 'var(--red)';
        html += `<li style="padding:7px 0">
          <div style="display:flex;align-items:center;gap:5px;margin-bottom:3px">
            <span class="small mono" style="color:var(--gold)">@${esc(author)}</span>
            <span class="small" style="color:var(--muted)">${esc(ptype)}</span>
            <span class="small mono" style="margin-left:auto;color:${relCol}">${rel}%</span>
          </div>
          <div class="small" style="color:var(--muted);margin-bottom:5px;line-height:1.3">${esc(sumDisp)}</div>
          <div style="display:flex;gap:5px;align-items:center">
            <button onclick="xintakeAction(${item.id},'approve')"
              style="font-size:10px;padding:2px 9px;background:rgba(74,222,128,0.15);color:var(--green);border:1px solid rgba(74,222,128,0.3);border-radius:3px;cursor:pointer;line-height:1.6">
              &#10003; approve</button>
            <button onclick="xintakeAction(${item.id},'reject')"
              style="font-size:10px;padding:2px 9px;background:var(--surface-2);color:var(--muted);border:1px solid var(--border);border-radius:3px;cursor:pointer;line-height:1.6">
              &#10007; reject</button>
            ${item.url ? `<a href="${esc(item.url)}" target="_blank" rel="noopener" style="font-size:10px;margin-left:auto;color:var(--gold-dim)">view &rarr;</a>` : ''}
          </div>
        </li>`;
      }
      html += '</ul>';
    } else if (pending === 0) {
      html += '<div class="small" style="color:var(--green);margin-top:4px">&#10003; queue clear</div>';
    }
    host.innerHTML = html;
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  X INTAKE FULL PAGE
  // ══════════════════════════════════════════════════════════════════════════

  let _xiItems  = [];
  let _xiOffset = 0;
  let _xiTotal  = 0;
  let _xiFilter = { status: '', dateFrom: '', dateTo: '' };

  async function loadXIntake(reset) {
    if (reset !== false) { _xiOffset = 0; _xiItems = []; }
    const { status, dateFrom, dateTo } = _xiFilter;
    let url = `/api/x-intake/items?limit=${XI_PG_SIZE}&offset=${_xiOffset}`;
    if (status)   url += '&status='    + encodeURIComponent(status);
    if (dateFrom) url += '&date_from=' + encodeURIComponent(dateFrom);
    if (dateTo)   url += '&date_to='   + encodeURIComponent(dateTo);
    if (reset !== false) $('xi-items').innerHTML = '<div class="unavailable">loading…</div>';
    const data  = await fetchJson(url);
    if (!data) { $('xi-items').innerHTML = unavail('failed to load — is x-intake DB mounted?'); return; }
    const incoming = data.items || [];
    _xiItems  = (reset !== false) ? incoming : [..._xiItems, ...incoming];
    _xiTotal  = data.total || 0;
    _xiOffset += incoming.length;
    // Stats
    const stats = await fetchJson('/api/x-intake/stats');
    if (stats) { renderXiStats(stats); }
    renderXiItems(_xiItems);
    $('xi-count-label').textContent =
      _xiItems.length + ' of ' + _xiTotal + ' items' +
      (status ? ' · filtered: ' + status : '') +
      (dateFrom || dateTo ? ' · ' + (dateFrom || '…') + ' → ' + (dateTo || '…') : '');
    $('xi-load-more').style.display = (_xiOffset < _xiTotal) ? 'flex' : 'none';
  }

  window.loadXIntake     = () => loadXIntake(true);
  window.loadMoreXIntake = () => loadXIntake(false);

  function renderXiStats(s) {
    $('xi-s-pending').textContent  = s.pending       ?? '—';
    $('xi-s-approved').textContent = s.approved      ?? '—';
    $('xi-s-auto').textContent     = s.auto_approved ?? '—';
    $('xi-s-rejected').textContent = (s.rejected||0) + (s.auto_rejected||0);
    $('xi-s-total').textContent    = s.total         ?? '—';
    _updateNavBadge(s.pending || 0);
  }

  // ── Contact context section for xi-items ───────────────────────────────────
  const _XI_RT_COLORS = {client:'#60a5fa',vendor:'#a78bfa',builder:'#34d399',
    trade_partner:'#fbbf24',internal_team:'#94a3b8',personal_work_related:'#f472b6'};

  function renderXiContextSection(item) {
    if (!item.context_json) return '';
    let ctx;
    try { ctx = JSON.parse(item.context_json); } catch(e) { return ''; }
    if (!ctx || !ctx.status) return '';

    if (ctx.status === 'no_profile' || ctx.status === 'no_handle') {
      return `<div class="xi-ctx-card xi-ctx-no-profile">
        <span style="font-size:10px;color:var(--muted);">📭 No approved profile — review thread for Client Intelligence.</span>
      </div>`;
    }
    if (ctx.status !== 'ok') return '';

    const p = ctx.profile || {};
    const rtColor  = _XI_RT_COLORS[p.relationship_type] || 'var(--muted)';
    const rtLabel  = (p.relationship_type || '').replace(/_/g,' ').toUpperCase();
    const systems  = (p.systems_or_topics || []).slice(0,4).join(', ');
    const openReqs = (p.open_requests || []).slice(0,2);
    const conf     = ((ctx.confidence || 0) * 100).toFixed(0);
    const confColor = ctx.confidence >= 0.75 ? 'var(--green)' : ctx.confidence >= 0.50 ? 'var(--yellow)' : 'var(--muted)';
    const unverifiedCount = Object.values(ctx.unverified_facts || {}).reduce((s,a) => s + a.length, 0);
    const actionId = esc(ctx.action_id || '');
    const contactMasked = esc(ctx.contact_masked || '');
    // Stable element id scoped to the queue item
    const ctxId = 'xictx-' + (item.id || Math.random().toString(36).slice(2));

    let h = `<div class="xi-ctx-card" id="${ctxId}">`;

    // Header row: relationship type, contact, confidence
    h += `<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">`;
    h += `<span style="font-size:9px;font-weight:700;color:${rtColor};">${esc(rtLabel)}</span>`;
    h += `<span class="mono" style="font-size:9px;color:var(--muted);">${contactMasked}</span>`;
    h += `<span style="font-size:9px;font-weight:600;color:${confColor};margin-left:auto;">${conf}% confidence</span>`;
    h += `</div>`;

    // Profile summary + signals
    if (p.summary) h += `<div style="font-size:10px;color:var(--text);margin-bottom:2px;">${esc(p.summary.slice(0,120))}</div>`;
    if (systems)   h += `<div style="font-size:9px;color:var(--muted);">systems: ${esc(systems)}</div>`;
    if (openReqs.length) {
      h += `<div style="font-size:9px;color:var(--yellow);margin-top:2px;">open: ${esc(openReqs.join(' · ').slice(0,100))}</div>`;
    }
    if (unverifiedCount) {
      h += `<div style="font-size:9px;color:var(--muted);font-style:italic;margin-top:2px;">${unverifiedCount} unverified fact(s)</div>`;
    }
    if (ctx.suggested_next_action) {
      h += `<div style="font-size:10px;color:var(--blue);margin-top:4px;border-left:2px solid var(--blue);padding-left:5px;">${esc(ctx.suggested_next_action.slice(0,100))}</div>`;
    }

    // Draft reply + reasoning toggle
    if (ctx.draft_reply) {
      const draftEsc = esc(ctx.draft_reply.slice(0,400));
      const reasonEsc = esc(ctx.reasoning || '');

      h += `<div style="margin-top:6px;border:1px solid var(--border);border-radius:4px;padding:6px 8px;background:var(--surface-2);">`;
      h += `<div style="font-size:9px;font-weight:700;color:var(--gold-dim);text-transform:uppercase;letter-spacing:.4px;margin-bottom:3px;">Draft Reply</div>`;

      // Editable textarea (hidden by default, shown for Edit+Approve)
      h += `<div id="${ctxId}-draft-display" style="font-size:10px;color:var(--text);white-space:pre-wrap;margin-bottom:4px;">${draftEsc}</div>`;
      h += `<textarea id="${ctxId}-draft-edit" rows="3" style="display:none;width:100%;font-size:10px;padding:4px;background:var(--surface);color:var(--text);border:1px solid var(--border-2);border-radius:3px;resize:vertical;box-sizing:border-box;">${draftEsc}</textarea>`;

      // Reasoning toggle
      if (reasonEsc) {
        h += `<details style="margin-bottom:5px;"><summary style="font-size:9px;color:var(--muted);cursor:pointer;">why this reply ▸</summary>`;
        h += `<div style="font-size:9px;color:var(--muted);margin-top:3px;font-style:italic;">${reasonEsc}</div>`;
        h += `</details>`;
      }

      // Source facts (collapsed)
      if (ctx.source_facts && ctx.source_facts.length) {
        h += `<details style="margin-bottom:5px;"><summary style="font-size:9px;color:var(--muted);cursor:pointer;">source facts (${ctx.source_facts.length}) ▸</summary><div style="margin-top:3px;">`;
        ctx.source_facts.forEach((sf) => {
          const tag = sf.verified ? '<span style="color:var(--green);font-size:8px;">✓</span>' : '<span style="color:var(--yellow);font-size:8px;">~</span>';
          h += `<div style="font-size:9px;color:var(--muted);">${tag} ${esc(sf.fact_type)}: ${esc(sf.fact_value.slice(0,60))}</div>`;
        });
        h += `</div></details>`;
      }

      // Approval buttons
      h += `<div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:4px;">`;
      h += `<button disabled title="Auto-send is disabled — use Approve Only or Edit+Approve"
               style="font-size:9px;padding:2px 8px;border-radius:3px;border:1px solid var(--border-2);background:transparent;color:var(--muted);cursor:not-allowed;">
               ✉ Approve &amp; Send (disabled)</button>`;
      h += `<button onclick="approveReply('${ctxId}','${actionId}','${contactMasked}','approve_only')"
               style="font-size:9px;padding:2px 9px;border-radius:3px;border:1px solid var(--green);background:transparent;color:var(--green);cursor:pointer;">
               ✓ Approve Only</button>`;
      h += `<button onclick="approveReply('${ctxId}','${actionId}','${contactMasked}','edit_approve')"
               id="${ctxId}-edit-btn"
               style="font-size:9px;padding:2px 9px;border-radius:3px;border:1px solid var(--blue);background:transparent;color:var(--blue);cursor:pointer;">
               ✎ Edit + Approve</button>`;
      h += `</div>`;
      h += `<div id="${ctxId}-status" style="font-size:9px;margin-top:3px;display:none;"></div>`;
      h += `</div>`;  // end draft box
    }

    h += `</div>`;  // end xi-ctx-card
    return h;
  }

  // ── Reply approval handler ─────────────────────────────────────────────────
  window.approveReply = async function(ctxId, actionId, contactMasked, mode) {
    const statusEl   = document.getElementById(ctxId + '-status');
    const displayEl  = document.getElementById(ctxId + '-draft-display');
    const editEl     = document.getElementById(ctxId + '-draft-edit');
    const editBtn    = document.getElementById(ctxId + '-edit-btn');

    if (mode === 'edit_approve') {
      // First click: toggle to edit mode
      if (editEl && editEl.style.display === 'none') {
        if (displayEl) displayEl.style.display = 'none';
        editEl.style.display = 'block';
        editEl.focus();
        if (editBtn) { editBtn.textContent = '✓ Confirm Edit'; editBtn.style.color = 'var(--green)'; editBtn.style.borderColor = 'var(--green)'; }
        return;
      }
      // Second click: confirm with edit
    }

    const draftReply = displayEl ? displayEl.textContent : '';
    const editedReply = (editEl && editEl.style.display !== 'none') ? editEl.value.trim() : '';
    const finalReply  = editedReply || draftReply;

    if (!finalReply) { if (statusEl) { statusEl.textContent = 'No reply text.'; statusEl.style.display = 'block'; } return; }

    if (statusEl) { statusEl.textContent = 'Saving…'; statusEl.style.color = 'var(--muted)'; statusEl.style.display = 'block'; }

    try {
      const r = await fetch('/api/x-intake/approve-reply', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          action_id:      actionId,
          approved:       true,
          draft_reply:    draftReply.slice(0,500),
          edited_reply:   editedReply.slice(0,500),
          contact_masked: contactMasked,
          confidence:     0,
        }),
      });
      const d = await r.json();
      if (d.status === 'ok') {
        if (statusEl) {
          statusEl.textContent = d.edited ? '✓ Edited reply approved (not sent)' : '✓ Reply approved (not sent)';
          statusEl.style.color = 'var(--green)'; statusEl.style.display = 'block';
        }
        if (editEl) editEl.style.display = 'none';
        if (displayEl) { displayEl.style.display = 'block'; if (editedReply) displayEl.textContent = editedReply; }
        if (editBtn) { editBtn.disabled = true; editBtn.style.opacity = '0.4'; }
      } else {
        if (statusEl) { statusEl.textContent = 'Error: ' + (d.error || d.message || 'unknown'); statusEl.style.color = 'var(--red)'; statusEl.style.display = 'block'; }
      }
    } catch(e) {
      if (statusEl) { statusEl.textContent = 'Network error.'; statusEl.style.color = 'var(--red)'; statusEl.style.display = 'block'; }
    }
  };

  function renderXiItems(items) {
    const host = $('xi-items');
    if (!items.length) { host.innerHTML = '<div class="xi-empty">No items match the current filter.</div>'; return; }
    host.innerHTML = items.map((item) => {
      const rel       = item.relevance || 0;
      const ts        = fmtTs(item.created_at);
      const reviewTs  = item.reviewed_at ? ' · reviewed ' + timeAgo(item.reviewed_at) : '';
      const hasTr     = item.has_transcript ? '🎬 ' : '';
      const canAction = item.status === 'pending';
      const sumDisp   = extractSummary(item.summary);
      const ctxHtml   = renderXiContextSection(item);
      return `<div class="xi-item status-${esc(item.status||'unknown')}" id="xi-item-${item.id}">
  <div class="xi-item-header">
    <span class="xi-item-author">${hasTr}@${esc(item.author||'?')}</span>
    <span class="badge-type ${typeClass(item.post_type)}">${esc(item.post_type||'info')}</span>
    <span class="badge-status ${statusClass(item.status)}">${esc(item.status||'?')}</span>
    <div class="xi-item-meta">
      <span class="${relClass(rel)} mono" style="font-size:12px;font-weight:600">${rel}%</span>
      <span class="xi-item-ts">${esc(ts)}${esc(reviewTs)}</span>
    </div>
  </div>
  ${sumDisp ? `<div class="xi-item-summary">${esc(sumDisp)}</div>` : ''}
  ${item.review_note ? `<div class="small" style="color:var(--muted);margin-top:3px;font-style:italic">Note: ${esc((item.review_note||'').slice(0,140))}</div>` : ''}
  ${ctxHtml}
  <div class="xi-item-actions">
    ${canAction
      ? `<button class="btn approve" onclick="xiAction(${item.id},'approve')">&#10003; Approve</button>
         <button class="btn reject"  onclick="xiAction(${item.id},'reject')">&#10007; Reject</button>
         <input class="xi-note" id="xi-note-${item.id}" placeholder="optional note…" type="text" />`
      : ''}
    ${item.url ? `<a class="btn" href="${esc(item.url)}" target="_blank" rel="noopener" style="${canAction?'margin-left:auto':''}color:var(--gold-dim)">view &rarr;</a>` : ''}
    ${item.has_transcript ? `<button class="btn" onclick="switchTab('transcripts');selectTranscript(${item.id})">📝 transcript</button>` : ''}
  </div>
</div>`;
    }).join('');
  }

  window.xiAction = async function xiAction(id, action) {
    const noteEl = $('xi-note-' + id);
    const note   = noteEl ? noteEl.value.trim() : '';
    const el     = $('xi-item-' + id);
    if (el) el.style.opacity = '0.45';
    const result = await postJson('/api/x-intake/' + id + '/' + action, { note });
    if (!el) return;
    el.style.opacity = '1';
    if (result && result.ok !== false) {
      // In-place update — remove old status class, apply new
      el.classList.forEach((c) => { if (c.startsWith('status-')) el.classList.remove(c); });
      el.classList.add('status-' + action);
      const sb = el.querySelector('.badge-status');
      if (sb) { sb.className = 'badge-status ' + statusClass(action); sb.textContent = action; }
      const actions = el.querySelector('.xi-item-actions');
      if (actions) {
        el.querySelectorAll('.btn.approve, .btn.reject, .xi-note').forEach((n) => n.remove());
      }
      // Refresh stats
      const stats = await fetchJson('/api/x-intake/stats');
      if (stats) renderXiStats(stats);
    } else {
      alert('Action failed: ' + (result?.error || 'unknown error'));
    }
  };

  // Filter tab wiring
  document.querySelectorAll('.xi-status-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.xi-status-tab').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      _xiFilter.status = btn.dataset.status || '';
      loadXIntake(true);
    });
  });
  $('xi-date-from').addEventListener('change', () => {
    _xiFilter.dateFrom = $('xi-date-from').value;
    loadXIntake(true);
  });
  $('xi-date-to').addEventListener('change', () => {
    _xiFilter.dateTo = $('xi-date-to').value;
    loadXIntake(true);
  });

  // ══════════════════════════════════════════════════════════════════════════
  //  TRANSCRIPTS & GEMS
  // ══════════════════════════════════════════════════════════════════════════

  let _trSelected = null;

  async function loadTranscripts() {
    $('tr-list').innerHTML = '<div class="unavailable" style="padding:20px">loading…</div>';
    const data = await fetchJson('/api/transcripts?limit=100');
    if (!data || data.error) {
      $('tr-list').innerHTML = `<div class="unavailable" style="padding:20px">${esc(data?.error||'unavailable')}</div>`;
      return;
    }
    renderTrList(data.transcripts || []);
  }

  window.loadTranscripts = loadTranscripts;

  function renderTrList(items) {
    if (!items.length) {
      $('tr-list').innerHTML = '<div class="unavailable" style="padding:20px">no transcripts yet</div>';
      return;
    }
    $('tr-list').innerHTML = items.map((item) => {
      const rel       = item.relevance || 0;
      const ts        = fmtTs(item.created_at);
      const aLabel    = item.analyzed === 1 ? '✓ analyzed' : item.analyzed === 2 ? '✗ failed' : 'unanalyzed';
      const aStyle    = item.analyzed === 1 ? 'color:var(--green)' : item.analyzed === 2 ? 'color:var(--red)' : 'color:var(--muted)';
      const snippet   = extractSummary(item.summary).slice(0, 55);
      const selected  = _trSelected === item.id;
      return `<div class="tr-item${selected?' selected':''}" id="tr-li-${item.id}" onclick="selectTranscript(${item.id})">
  <div class="tr-item-author">@${esc(item.author||'?')}</div>
  <div class="tr-item-meta">
    <span class="badge-type ${typeClass(item.post_type)}">${esc(item.post_type||'info')}</span>
    <span class="${relClass(rel)} mono" style="font-size:10px">${rel}%</span>
    <span style="font-size:10px;${aStyle}">${aLabel}</span>
  </div>
  ${snippet ? `<div class="tr-item-snippet">${esc(snippet)}</div>` : ''}
  <div class="small" style="margin-top:3px">${esc(ts)}</div>
</div>`;
    }).join('');
  }

  window.selectTranscript = async function selectTranscript(id) {
    _trSelected = id;
    document.querySelectorAll('.tr-item').forEach((el) => el.classList.remove('selected'));
    const li = $('tr-li-' + id);
    if (li) li.classList.add('selected');
    const detail = $('tr-detail');
    detail.innerHTML = '<div class="unavailable" style="min-height:200px;display:flex;align-items:center;justify-content:center">loading…</div>';
    const data = await fetchJson('/api/transcripts/' + id);
    if (!data || data.error) {
      detail.innerHTML = `<div class="unavailable">${esc(data?.error||'failed to load')}</div>`;
      return;
    }
    renderTrDetail(detail, data);
  };

  function renderTrDetail(host, data) {
    const item       = data.item || {};
    const author     = item.author || '?';
    const rel        = item.relevance || 0;
    const ts         = fmtTs(item.created_at);
    const summary    = data.parsed_summary || extractSummary(item.summary || '');
    const transcript = data.parsed_transcript || '';
    const flags      = data.flags || [];
    const quotes     = data.key_quotes || [];
    const strats     = data.strategies || '';
    const gems       = data.gems || [];
    const url        = item.url || '';

    let html = `<div class="tr-detail-header">
  <div class="tr-detail-author">@${esc(author)}</div>
  <div class="tr-detail-badges">
    <span class="badge-type ${typeClass(item.post_type)}">${esc(item.post_type||'info')}</span>
    <span class="badge-status ${statusClass(item.status)}">${esc(item.status||'?')}</span>
    <span class="${relClass(rel)} mono" style="font-size:12px;font-weight:600">${rel}% relevance</span>
    <span class="small">${esc(ts)}</span>
    ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener" style="font-size:11px;color:var(--gold-dim)">view post →</a>` : ''}
  </div>
</div>`;

    if (summary) html += `<div class="tr-section">
  <div class="tr-section-title">📋 Summary</div>
  <div class="tr-summary-text">${esc(summary)}</div>
</div>`;

    if (flags.length) html += `<div class="tr-section">
  <div class="tr-section-title">🏷 Flags</div>
  <div class="tr-flags">${flags.map((f) => `<span class="tr-flag">${esc(f)}</span>`).join('')}</div>
</div>`;

    if (quotes.length) html += `<div class="tr-section">
  <div class="tr-section-title">💬 Key Quotes</div>
  <div class="tr-quotes">${quotes.slice(0,6).map((q) => `<div class="tr-quote">${esc(q)}</div>`).join('')}</div>
</div>`;

    if (strats) html += `<div class="tr-section">
  <div class="tr-section-title">♟ Strategies</div>
  <div class="small" style="white-space:pre-wrap;line-height:1.6;color:var(--text)">${esc(strats.slice(0,800))}</div>
</div>`;

    if (gems.length) {
      html += `<div class="tr-section">
  <div class="tr-section-title">💎 Hidden Gems — from Cortex deep analysis</div>
  <div class="tr-gems">`;
      for (const gem of gems.slice(0, 6)) {
        const gAge = gem.created_at ? 'analyzed ' + timeAgo(gem.created_at) : '';
        html += `<div class="tr-gem">
  <div class="tr-gem-title">${esc((gem.title||'').slice(0,120))}</div>
  <div class="tr-gem-content">${esc((gem.content||'').slice(0,600))}</div>
  ${gAge ? `<div class="tr-gem-meta"><span class="small">${esc(gAge)}</span></div>` : ''}
</div>`;
      }
      html += `</div></div>`;
    }

    // Collapsible full transcript
    const uid = 'tr-tx-' + item.id;
    html += `<div class="tr-section">
  <div class="tr-section-title">📝 Full Transcript</div>`;
    if (transcript) {
      html += `<div class="tr-transcript-toggle" onclick="toggleTx('${uid}')">
    <span class="arrow">▶</span>
    <span>Show transcript (${transcript.length.toLocaleString()} chars)</span>
  </div>
  <div class="tr-transcript-body" id="${uid}">${esc(transcript.slice(0, 20000))}</div>`;
    } else {
      html += `<div class="small" style="color:var(--muted);font-style:italic">
    ${item.transcript_path
      ? 'Transcript file at <code>' + esc(item.transcript_path) + '</code> is not readable from the Cortex container — check data volume mount.'
      : 'No transcript file recorded for this item.'}
  </div>`;
    }
    html += `</div>`;

    host.innerHTML = html;
  }

  window.toggleTx = function toggleTx(uid) {
    const body   = $(uid);
    const toggle = body && body.previousElementSibling;
    if (!body) return;
    body.classList.toggle('open');
    if (toggle) toggle.classList.toggle('open');
  };

  // ══════════════════════════════════════════════════════════════════════════
  //  DASHBOARD AUDIT SUMMARY
  // ══════════════════════════════════════════════════════════════════════════

  function renderTodayNeedsAttention(watchdog, followups, xiStats, emails, exposure, auditSummary) {
    const host = $('today-needs-attention');
    if (!host) return;

    const items = [];

    // Watchdog degraded services
    const degraded = (watchdog && watchdog.services)
      ? watchdog.services.filter((s) => s.state === 'degraded' || s.state === 'stale')
      : [];
    if (degraded.length > 0) {
      items.push({
        level: 'red',
        label: `${degraded.length} service${degraded.length !== 1 ? 's' : ''} degraded`,
        detail: degraded.map((s) => esc(s.name)).join(', '),
        tab: 'overview',
      });
    }

    // Overdue follow-ups
    const overdueFollowups = (followups && Array.isArray(followups.followups))
      ? followups.followups.filter((f) => f.overdue || f.status === 'overdue')
      : [];
    if (overdueFollowups.length > 0) {
      items.push({
        level: 'yellow',
        label: `${overdueFollowups.length} overdue follow-up${overdueFollowups.length !== 1 ? 's' : ''}`,
        detail: overdueFollowups.slice(0, 2).map((f) => esc(f.name || f.client || '')).filter(Boolean).join(', '),
        tab: 'xintake',
      });
    }

    // X intake pending
    const xiPending = xiStats && xiStats.pending != null ? xiStats.pending : 0;
    if (xiPending > 0) {
      items.push({
        level: xiPending > 10 ? 'yellow' : 'green',
        label: `${xiPending} X intake item${xiPending !== 1 ? 's' : ''} pending`,
        detail: '',
        tab: 'xintake',
      });
    }

    // Unread emails
    const unreadEmails = emails && emails.unread != null ? emails.unread
      : (emails && Array.isArray(emails.emails)) ? emails.emails.filter((e) => !e.read).length : 0;
    if (unreadEmails > 0) {
      items.push({
        level: 'green',
        label: `${unreadEmails} unread email${unreadEmails !== 1 ? 's' : ''}`,
        detail: '',
        tab: 'overview',
      });
    }

    // Polymarket open positions
    const positions = exposure && exposure.positions != null ? exposure.positions : 0;
    const totalValue = exposure && exposure.total_value != null ? exposure.total_value : null;
    if (positions > 0) {
      items.push({
        level: 'green',
        label: `${positions} Polymarket position${positions !== 1 ? 's' : ''}`,
        detail: totalValue != null ? `${fmtUsd(totalValue)} exposure` : '',
        tab: 'money',
      });
    }

    // Audit failures
    const failingCount = auditSummary && auditSummary.failing_sections
      ? auditSummary.failing_sections.length : 0;
    if (failingCount > 0) {
      items.push({
        level: 'red',
        label: `${failingCount} dashboard endpoint${failingCount !== 1 ? 's' : ''} failing`,
        detail: '',
        tab: 'debug',
      });
    }

    if (items.length === 0) {
      host.innerHTML = `<div style="color:var(--green);font-weight:600;font-size:13px;">All clear — nothing needs attention right now.</div>`;
      return;
    }

    const _levelColor = (l) => l === 'red' ? 'var(--red)' : l === 'yellow' ? 'var(--yellow)' : 'var(--green)';

    host.innerHTML = items.map((item) => `
      <div style="display:flex;align-items:baseline;gap:8px;padding:5px 0;border-bottom:1px solid var(--border);">
        <span style="width:6px;height:6px;border-radius:50%;background:${_levelColor(item.level)};flex-shrink:0;margin-top:4px;display:inline-block;"></span>
        <span style="font-weight:600;font-size:12px;color:var(--text);">
          <a href="#" onclick="switchTab('${esc(item.tab)}');return false;" style="color:inherit;text-decoration:none;">${esc(item.label)}</a>
        </span>
        ${item.detail ? `<span class="small" style="color:var(--muted);">${item.detail}</span>` : ''}
      </div>`).join('');
  }

  function renderSafeToFund(exposure) {
    const host = $('safe-to-fund');
    const card = $('safe-to-fund-card');
    if (!host) return;

    // Static blockers from audit (known at build time)
    const staticBlockers = [
      { label: 'On-chain balance below circuit breaker', detail: '$3.72 on-chain < $7.50 minimum', resolved: false },
      { label: 'No 48h paper simulation completed', detail: 'Required before live funding', resolved: false },
      { label: 'EIP-712 signing not live-validated', detail: 'Must be verified end-to-end first', resolved: false },
      { label: '78 legacy positions pending resolution', detail: 'Must resolve or document before adding capital', resolved: false },
    ];

    const unresolvedCount = staticBlockers.filter((b) => !b.resolved).length;
    const safe = unresolvedCount === 0;

    if (card) {
      if (!safe) card.style.borderLeftColor = 'var(--red)';
      else card.style.borderLeftColor = 'var(--green)';
    }

    // Live exposure from API
    const livePositions = exposure && exposure.positions != null ? exposure.positions : null;
    const liveValue = exposure && exposure.total_value != null ? exposure.total_value : null;
    const liveRow = (livePositions != null)
      ? `<div style="margin-bottom:10px;font-size:12px;color:var(--muted);">Live: ${livePositions} open position${livePositions !== 1 ? 's' : ''} · ${liveValue != null ? fmtUsd(liveValue) : '—'} exposure</div>`
      : '';

    host.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
        <span style="font-size:22px;font-weight:900;color:${safe ? 'var(--green)' : 'var(--red)'};">${safe ? 'SAFE TO FUND' : 'NOT SAFE TO FUND'}</span>
        <span class="card-badge ${safe ? 'badge-live' : 'badge-unavail'}">${safe ? 'CLEAR' : 'BLOCKED'}</span>
      </div>
      ${liveRow}
      <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:6px;">${unresolvedCount} blocker${unresolvedCount !== 1 ? 's' : ''} remaining</div>
      ${staticBlockers.map((b) => `
        <div style="display:flex;align-items:baseline;gap:8px;padding:4px 0;border-bottom:1px solid var(--border);">
          <span style="color:${b.resolved ? 'var(--green)' : 'var(--red)'};font-size:12px;">${b.resolved ? '✓' : '✗'}</span>
          <span>
            <span style="font-size:12px;font-weight:600;color:var(--text);">${esc(b.label)}</span>
            <span class="small" style="color:var(--muted);display:block;">${esc(b.detail)}</span>
          </span>
        </div>`).join('')}`;
  }

  function renderDashboardAudit(data) {
    const host = $('dashboard-audit');
    const card = $('dashboard-audit-card');
    if (!data) { host.innerHTML = unavail(); return; }

    const live    = (data.live_sections    || []).length;
    const failing = (data.failing_sections || []).length;
    const stale   = (data.stale_sections   || []).length;
    const debug   = (data.debug_only_sections || []).length;
    const planned = (data.planned_sections || []).length;
    const recCount  = data.recommendation_count  ?? 0;
    const fixCount  = data.fixes_applied_count   ?? 0;

    if (card) {
      if (failing > 0) card.classList.add('alert');
      else card.classList.remove('alert');
    }

    const _prioColor = (p) =>
      p === 'P1' ? 'var(--red)' : p === 'P2' ? 'var(--yellow)' : 'var(--muted)';

    const _sectionRows = (entries, showPrio) =>
      (entries || []).map((e) => `
        <tr>
          <td style="font-weight:500;font-size:11px;color:var(--text);">${esc(e.section)}</td>
          <td class="small mono" style="color:var(--muted)">${esc(e.endpoint)}</td>
          ${showPrio ? `<td style="font-size:10px;font-weight:700;color:${_prioColor(e.priority)}">${esc(e.priority||'')}</td>` : '<td></td>'}
          <td class="small" style="color:var(--muted);max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(e.reason)}">${esc((e.reason||'').slice(0,70))}</td>
        </tr>`).join('');

    const _section = (title, entries, showPrio, borderColor) => {
      if (!entries || !entries.length) return '';
      return `
        <div style="margin-top:10px;">
          <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:${borderColor};margin-bottom:4px;">${esc(title)}</div>
          <table style="width:100%;border-collapse:collapse;border-left:2px solid ${borderColor};padding-left:6px;">
            <tbody>${_sectionRows(entries, showPrio)}</tbody>
          </table>
        </div>`;
    };

    const asOf = data.as_of ? `<div class="small" style="color:var(--muted);margin-top:6px;">audited ${timeAgo(data.as_of)}</div>` : '';
    const auditFile = 'ops/verification/20260427T180800Z-cortex-dashboard-audit.md';

    host.innerHTML = `
      <div class="stat-row" style="flex-wrap:wrap;gap:8px;">
        <div><div class="stat-big" style="color:var(--green)">${live}</div><div class="stat-label">live</div></div>
        <div><div class="stat-big" style="color:${failing>0?'var(--red)':'var(--text)'}">${failing}</div><div class="stat-label">failing</div></div>
        <div><div class="stat-big" style="color:${stale>0?'var(--yellow)':'var(--text)'}">${stale}</div><div class="stat-label">stale</div></div>
        <div><div class="stat-big" style="color:var(--muted)">${planned}</div><div class="stat-label">planned</div></div>
        <div><div class="stat-big" style="color:var(--green)">${fixCount}</div><div class="stat-label">fixed</div></div>
      </div>
      ${_section('Failing', data.failing_sections, true, 'var(--red)')}
      ${_section('Stale / Misleading', data.stale_sections, true, 'var(--yellow)')}
      ${_section('Debug-only (fixed)', data.debug_only_sections, false, 'var(--muted)')}
      ${_section('Planned (not built yet)', data.planned_sections, false, 'var(--blue)')}
      <div style="margin-top:10px;font-size:10px;color:var(--muted);">
        ${recCount} recommendation${recCount !== 1 ? 's' : ''} · ${fixCount} fix${fixCount !== 1 ? 'es' : ''} applied
      </div>
      <div style="margin-top:6px;font-size:10px;color:var(--muted);">
        Full report: <code style="font-size:9px;">${esc(auditFile)}</code>
      </div>
      ${asOf}`;
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  OVERVIEW REFRESH ORCHESTRATOR
  // ══════════════════════════════════════════════════════════════════════════

  async function refresh() {
    tickClock();
    const [
      services, wallet, positions, pnlSummary, activity,
      emails, calendar, followups, goals, health, memories,
      decisions, digest, system, redeemer,
      xiStats, xiQueue, meetings, calls, watchdog, exposure, auditSummary,
      dashConfig,
    ] = await Promise.all([
      fetchJson('/api/services'),
      fetchJson('/api/wallet'),
      fetchJson('/api/positions'),
      fetchJson('/api/pnl-summary'),
      fetchJson('/api/activity'),
      fetchJson('/api/emails'),
      fetchJson('/api/calendar'),
      fetchJson('/api/followups'),
      fetchJson('/goals'),
      fetchJson('/health'),
      fetchJson('/memories?limit=10'),
      fetchJson('/api/decisions/recent?limit=20'),
      fetchJson('/digest/today'),
      fetchJson('/api/system'),
      fetchJson('/api/redeemer'),
      fetchJson('/api/x-intake/stats'),
      fetchJson('/api/x-intake/queue?status=pending&limit=5'),
      fetchJson('/api/meetings/recent?limit=20'),
      fetchJson('/api/symphony/voice-receptionist'),
      fetchJson('/api/watchdog/status'),
      fetchJson('/api/polymarket/exposure'),
      fetchJson('/api/dashboard/audit-summary'),
      fetchJson('/api/dashboard/config'),
    ]);

    // Update global debug mode from server config (URL param ?debug=1 still overrides)
    if (dashConfig && !_debugMode) {
      _debugMode = Boolean(dashConfig.debug_mode);
    }

    renderServices(services);
    renderEmails(emails);
    renderCalendar(calendar);
    renderFollowups(followups);
    renderCalls(calls);
    renderWallet(wallet);
    renderPositions(positions);
    renderPnl(wallet, pnlSummary);
    renderActivity(activity);
    renderRedeemer(redeemer);
    renderMemory(health && health.memories, memories);
    renderGoals(goals);
    renderDecisions(decisions);
    renderXIntakeWidget(xiStats, xiQueue);
    renderMeetings(meetings);
    renderDigest(digest);
    renderWatchdog(watchdog);
    renderPolyExposure(exposure);
    renderDashboardAudit(auditSummary);
    renderTodayNeedsAttention(watchdog, followups, xiStats, emails, exposure, auditSummary);
    renderSafeToFund(exposure);
    renderFooter(health && health.memories, wallet, emails, system);

    $('refreshed').textContent = 'refreshed ' + new Date().toLocaleTimeString();
  }

  refresh();
  loadToolAccess('overview');
  setInterval(refresh, REFRESH_MS);
  setInterval(tickClock, 1000);

  // ══════════════════════════════════════════════════════════════════════════
  //  SYMPHONY OPS
  // ══════════════════════════════════════════════════════════════════════════

  async function loadSymphonyOps() {
    loadProposalTemplates();
    loadCortexStats();
    checkPortalHealth();
    loadVoiceReceptionist();
    loadXApiStatus();
    loadXInsights();
  }

  async function loadXInsights() {
    const data = await fetchJson('/api/x-api/insights?limit=10');
    renderXInsights(data);
  }

  function renderXInsights(data) {
    const host = $('x-insights-overview');
    if (!data) { host.innerHTML = unavail(); return; }

    if (data.status === 'no_db' || data.count === 0) {
      host.innerHTML = `<div class="small" style="color:var(--muted)">
        No insights extracted yet. Run:
        <code>python3 scripts/x_api_extract_insights.py --apply</code>
      </div>`;
      return;
    }

    const topicColor = t => ({
      smart_home: 'var(--green)', av: 'var(--gold)', ai_ml: 'var(--blue)',
      engineering: 'var(--purple, #9b8dff)', business: 'var(--yellow)',
    }[t] || 'var(--muted)');

    const typeLabel = t => ({
      troubleshooting_tip: '&#128736; fix', workflow_improvement: '&#9889; workflow',
      product_idea: '&#128161; idea', general_knowledge: '&#128218; knowledge',
    }[t] || t);

    const cards = data.insights.map(i => `
      <div style="border:1px solid var(--border);border-radius:6px;padding:10px 12px;margin-bottom:8px">
        <div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-bottom:4px">
          <span style="color:${topicColor(i.topic)};font-weight:600;font-size:0.8em;text-transform:uppercase;letter-spacing:0.05em">${esc(i.topic)}</span>
          <span class="small" style="color:var(--muted)">${typeLabel(i.insight_type)}</span>
          <span class="small" style="color:var(--muted);margin-left:auto">score ${(i.relevance_score || 0).toFixed(2)}</span>
        </div>
        <div style="font-size:0.9em;margin-bottom:4px">${esc(i.summary)}</div>
        ${i.source_url
          ? `<a href="${esc(i.source_url)}" target="_blank" rel="noopener" class="small" style="color:var(--gold)">${esc(i.source_url.slice(0, 70))}</a>`
          : (i.author_handle ? `<span class="small" style="color:var(--muted)">@${esc(i.author_handle)}</span>` : '')}
      </div>`).join('');

    host.innerHTML = `
      <div class="small" style="color:var(--muted);margin-bottom:8px">${esc(data.count)} insight${data.count !== 1 ? 's' : ''} extracted from eligible items</div>
      ${cards}
      <div class="small" style="color:var(--muted);margin-top:4px">
        Run: <code>python3 scripts/x_api_extract_insights.py --apply</code>
      </div>`;
  }

  async function loadXApiStatus() {
    const [status, items] = await Promise.all([
      fetchJson('/api/x-api/status'),
      fetchJson('/api/x-api/items?limit=5'),
    ]);
    renderXApi(status, items);
  }

  function renderXApi(status, items) {
    const host = $('x-api-overview');
    if (!status) { host.innerHTML = unavail(); return; }

    const enabled  = status.enabled;
    const creds    = status.credentials || {};
    const hasBearer = creds.bearer_token;
    const hasUserId = creds.user_id_configured;

    const credBadge = (ok, label) =>
      `<span class="small" style="margin-right:6px;color:${ok ? 'var(--green)' : 'var(--muted)'}">
        ${ok ? '&#10003;' : '&#10005;'} ${esc(label)}
      </span>`;

    const credLine = [
      credBadge(hasBearer, 'Bearer Token'),
      credBadge(creds.user_id_configured, 'User ID'),
      credBadge(creds.access_token, 'User Auth'),
    ].join('');

    const usedPct = status.daily_reads_limit > 0
      ? Math.round((status.daily_reads_used / status.daily_reads_limit) * 100) : 0;
    const usageColor = usedPct >= 90 ? 'var(--red)' : usedPct >= 70 ? 'var(--yellow)' : 'var(--green)';

    const statusBadge = enabled
      ? `<span style="color:var(--green);font-weight:600">ENABLED</span>`
      : `<span style="color:var(--muted)">DISABLED (X_ENABLED=0)</span>`;

    const warning = status.warning
      ? `<div class="small" style="color:var(--yellow);margin-top:4px">${esc(status.warning)}</div>` : '';

    const lastRun = status.last_run
      ? `<div class="small" style="color:var(--muted);margin-top:4px">Last run: ${esc(timeAgo(status.last_run))} via ${esc(status.last_run_endpoint || '')}</div>`
      : `<div class="small" style="color:var(--muted);margin-top:4px">No runs recorded yet</div>`;

    const recentItems = (items && items.items && items.items.length)
      ? `<ul style="margin-top:6px">${items.items.map(i =>
          `<li class="small" title="${esc(i.x_item_id)}">
            <span style="color:var(--muted)">[${esc(i.item_type)}]</span>
            ${i.url ? `<a href="${esc(i.url)}" target="_blank" style="color:var(--gold)">${esc((i.url).slice(0,60))}</a>` : esc((i.text || '').slice(0,60))}
          </li>`
        ).join('')}</ul>`
      : `<div class="small" style="color:var(--muted);margin-top:4px">No items stored yet</div>`;

    host.innerHTML = `
      <div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap">
        <span>${statusBadge}</span>
        <span class="small" style="color:var(--muted)">${esc(status.total_items || 0)} items · ${esc(status.pending_items || 0)} pending</span>
        <span class="small" style="color:${usageColor}">${esc(status.daily_reads_used || 0)}/${esc(status.daily_reads_limit || 100)} reads today</span>
      </div>
      <div style="margin-top:6px">${credLine}</div>
      ${warning}${lastRun}
      <div style="margin-top:8px"><strong class="small">Recent items:</strong>${recentItems}</div>
      <div class="small" style="color:var(--muted);margin-top:8px">
        Run: <code>python3 scripts/x_api_intake.py --dry-run</code>
      </div>`;
  }

  async function loadVoiceReceptionist() {
    const data = await fetchJson('/api/symphony/voice-receptionist');
    renderCallsSymphony(data);
  }

  async function checkMarkupHealth() {
    try {
      const r = await fetch('/api/symphony/markup/health', {signal: AbortSignal.timeout(5000)});
      const d = await r.json();
      if (d.status === 'online') {
        $('markup-frame').style.display = 'block';
        $('markup-offline').style.display = 'none';
        $('markup-status').textContent = 'online';
        $('markup-status').style.color = 'var(--green)';
      } else throw new Error(d.error || d.http_status || 'offline');
    } catch {
      $('markup-frame').style.display = 'none';
      $('markup-offline').style.display = 'block';
      $('markup-status').textContent = 'offline';
      $('markup-status').style.color = 'var(--red)';
    }
  }

  async function checkBlueBubblesHealth() {
    try {
      const r = await fetch('/api/symphony/bluebubbles/health', {signal: AbortSignal.timeout(6000)});
      const d = await r.json();
      const el = document.getElementById('bb-status');
      if (d.status === 'online') {
        el.textContent = 'online'; el.style.color = 'var(--green)';
        const pa = document.getElementById('bb-private-api');
        pa.textContent = d.private_api ? '✓ installed' : '✗ missing';
        pa.style.color = d.private_api ? 'var(--green)' : 'var(--red)';
        document.getElementById('bb-version').textContent = d.server_version || '—';
        const urlEl = document.getElementById('bb-url');
        urlEl.innerHTML = d.server_url ? `<a href="${d.server_url}" target="_blank" rel="noopener">${d.server_url}</a>` : '';
      } else {
        el.textContent = 'offline'; el.style.color = 'var(--red)';
        document.getElementById('bb-private-api').textContent = '—';
        document.getElementById('bb-version').textContent = '—';
        document.getElementById('bb-url').textContent = d.error || '';
      }
    } catch {
      const el = document.getElementById('bb-status');
      if (el) { el.textContent = 'offline'; el.style.color = 'var(--red)'; }
    }
  }

  async function loadProposalTemplates() {
    try {
      const r = await fetch('/api/symphony/proposals/templates');
      if (!r.ok) throw new Error();
      const data = await r.json();
      const sel = $('proposal-template');
      sel.innerHTML = '<option value="">Select template...</option>';
      (data.templates || []).forEach(t => {
        sel.innerHTML += `<option value="${esc(t)}">${esc(t.replace(/_/g,' '))}</option>`;
      });
      $('proposal-templates-count').textContent = (data.templates || []).length;
      $('proposal-service-status').textContent = 'online';
      $('proposal-service-status').style.color = 'var(--green)';
    } catch {
      $('proposal-service-status').textContent = 'offline';
      $('proposal-service-status').style.color = 'var(--red)';
    }
  }

  window.generateProposal = async function generateProposal() {
    const template = $('proposal-template').value;
    const client   = $('proposal-client').value.trim();
    const project  = $('proposal-project').value.trim();
    if (!template || !client) { alert('Select a template and enter client name'); return; }
    $('proposal-gen-btn').disabled = true;
    $('proposal-gen-btn').textContent = 'Generating...';
    try {
      const r = await fetch('/api/symphony/proposals/generate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({template, client_name: client, project_name: project || client + ' Project'})
      });
      const data = await r.json();
      const resultEl = $('proposal-result');
      resultEl.style.display = 'block';
      if (data.proposal_id) {
        resultEl.innerHTML = `<span style="color:var(--green)">Generated: ${esc(data.proposal_id)}</span>`;
      } else {
        resultEl.innerHTML = `<span style="color:var(--red)">Error: ${esc(data.detail || data.error || 'unknown')}</span>`;
      }
    } catch {
      $('proposal-result').style.display = 'block';
      $('proposal-result').innerHTML = '<span style="color:var(--red)">Failed to connect</span>';
    }
    $('proposal-gen-btn').disabled = false;
    $('proposal-gen-btn').textContent = 'Generate Proposal';
  };

  window.generateAgreement = async function generateAgreement() {
    const client  = $('agree-client').value.trim();
    const project = $('agree-project').value.trim();
    const items   = $('agree-items').value.trim();
    if (!client) { alert('Enter client name'); return; }
    const resultEl = $('agree-result');
    resultEl.style.display = 'block';
    resultEl.textContent = 'Generating...';
    try {
      const r = await fetch('/api/symphony/agreement/generate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({client, project, items})
      });
      const data = await r.json();
      if (data.error) {
        resultEl.innerHTML = `<span style="color:var(--red)">Error: ${esc(data.error)}</span>`;
      } else {
        resultEl.innerHTML = `<span style="color:var(--green)">${esc(data.output || 'Done')}</span>`;
      }
    } catch {
      resultEl.innerHTML = '<span style="color:var(--red)">Failed to connect</span>';
    }
  };

  async function checkPortalHealth() {
    const data = await fetchJson('/api/symphony/portal/health');
    const statusEl = $('portal-status');
    if (data && data.status === 'ok') {
      statusEl.textContent = 'online';
      statusEl.style.color = 'var(--green)';
    } else {
      statusEl.textContent = data ? ('status: ' + (data.status || 'unknown')) : 'offline';
      statusEl.style.color = 'var(--muted)';
    }
  }

  window.runTool = async function runTool(toolName) {
    const outputEl = $('tool-output');
    outputEl.style.display = 'block';
    outputEl.textContent = 'Running ' + toolName + '...';
    try {
      const r = await fetch('/api/symphony/tools/' + toolName, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'
      });
      const data = await r.json();
      if (data.error) {
        outputEl.textContent = 'Error: ' + data.error;
      } else {
        outputEl.textContent = (data.stdout || '') + (data.stderr ? '\n[stderr] ' + data.stderr : '');
      }
    } catch(e) {
      outputEl.textContent = 'Failed: ' + String(e);
    }
  };

  async function loadCortexStats() {
    const data = await fetchJson('/api/symphony/cortex/stats');
    if (!data) return;
    $('cortex-total').textContent = data.total        ?? '—';
    $('cortex-goals').textContent = data.active_goals ?? '—';
    $('cortex-rules').textContent = data.rules        ?? '—';
  }

  window.triggerImprovement = async function triggerImprovement() {
    const digestEl = $('cortex-digest');
    digestEl.style.display = 'block';
    digestEl.textContent = 'Running improvement cycle...';
    try {
      const r = await fetch('/improve/run', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
      const data = await r.json();
      digestEl.textContent = data.result || data.message || JSON.stringify(data);
    } catch(e) {
      digestEl.textContent = 'Failed: ' + String(e);
    }
  };

  window.loadSymphonyDigest = async function loadSymphonyDigest() {
    const digestEl = $('cortex-digest');
    digestEl.style.display = 'block';
    digestEl.textContent = 'Loading digest...';
    const data = await fetchJson('/digest/today');
    if (!data) { digestEl.textContent = 'unavailable'; return; }
    const s = data.summary || data.headline || data.digest || '';
    digestEl.textContent = s || 'No digest available';
  };

  // ══════════════════════════════════════════════════════════════════════════
  //  AUTONOMY CONTROL PLANE
  // ══════════════════════════════════════════════════════════════════════════

  const _STATUS_ICON = { ok: '&#10003;', warn: '&#9888;', fail: '&#10007;', unknown: '?' };
  const _STATUS_COLOR = { ok: 'var(--green)', warn: 'var(--yellow)', fail: 'var(--red)', unknown: 'var(--muted)' };

  function _verdictColor(v) {
    if (!v) return 'var(--muted)';
    if (v === 'PASS' || v === 'CLOSED') return 'var(--green)';
    if (v === 'FAIL') return 'var(--red)';
    if (v === 'GAP' || v === 'PARTIAL') return 'var(--yellow)';
    if (v === 'NEEDS_MATT' || v === 'ARMED') return 'var(--purple)';
    return 'var(--muted)';
  }

  function renderAutonomy(data) {
    if (!data || data.error) {
      $('autonomy-badge').textContent = 'error';
      $('autonomy-badge').style.color = 'var(--red)';
      $('autonomy-questions').innerHTML = unavail(data?.error || 'failed to load');
      $('autonomy-gates').innerHTML = unavail();
      $('autonomy-verifs').innerHTML = unavail();
      return;
    }

    // Badge
    const overall = data.overall_status || 'unknown';
    const badge = $('autonomy-badge');
    badge.textContent = overall.toUpperCase();
    badge.style.color = _STATUS_COLOR[overall] || 'var(--muted)';
    badge.style.borderColor = _STATUS_COLOR[overall] || 'var(--border)';
    $('autonomy-ts').textContent = data.generated_at ? 'as of ' + timeAgo(data.generated_at) : '';

    // Nav badge (only truly-human gates)
    const gateCount = (data.human_gates || []).filter(
      (g) => ['NEEDS_MATT','APPROVAL_REQUIRED','WAITING_EXTERNAL'].includes(g.action_class)
    ).length;
    const navBadge = $('nav-autonomy-gates');
    if (gateCount > 0) { navBadge.textContent = gateCount; navBadge.classList.remove('hidden'); }
    else navBadge.classList.add('hidden');

    // Questions grid
    const qs = data.questions || [];
    if (!qs.length) {
      $('autonomy-questions').innerHTML = unavail('no questions returned');
    } else {
      $('autonomy-questions').innerHTML = '<ul>' + qs.map((q) => {
        const ic = _STATUS_ICON[q.status] || '?';
        const col = _STATUS_COLOR[q.status] || 'var(--muted)';
        return `<li style="padding:6px 0;display:grid;grid-template-columns:18px 1fr;gap:8px;align-items:start;">
          <span style="color:${col};font-weight:700;font-size:13px;">${ic}</span>
          <div>
            <div style="font-size:12px;color:var(--text);margin-bottom:2px;">${esc(q.label)}</div>
            <div class="small" style="color:var(--muted);line-height:1.4;">${esc(q.detail)}</div>
          </div>
        </li>`;
      }).join('') + '</ul>';
    }

    // Human gates — grouped by action_class
    const gates = data.human_gates || [];
    const gatesCard = $('autonomy-gates-card');
    const summary = data.gate_summary || {};
    const humanBlocked = (summary['NEEDS_MATT']||0) + (summary['APPROVAL_REQUIRED']||0) + (summary['WAITING_EXTERNAL']||0);
    $('autonomy-gates-count').textContent = gates.length ? `(${gates.length} open)` : '';
    if (humanBlocked > 0) gatesCard.classList.add('alert'); else gatesCard.classList.remove('alert');

    const _ACTION_COLOR = {
      'NEEDS_MATT':        'var(--red)',
      'APPROVAL_REQUIRED': 'var(--red)',
      'WAITING_EXTERNAL':  'var(--yellow)',
      'AUTO_REVIEW':       'var(--blue)',
      'AUTO_FIX':          'var(--green)',
    };
    const _ACTION_ORDER = ['NEEDS_MATT','APPROVAL_REQUIRED','WAITING_EXTERNAL','AUTO_REVIEW','AUTO_FIX'];

    if (!gates.length) {
      $('autonomy-gates').innerHTML = '<div class="small" style="color:var(--green)">&#10003; no open gates</div>';
    } else {
      // Build summary chips + grouped list
      const chips = _ACTION_ORDER.filter((k) => summary[k]).map((k) => {
        const col = _ACTION_COLOR[k] || 'var(--muted)';
        return `<span style="display:inline-block;font-size:10px;font-weight:700;color:${col};border:1px solid ${col};border-radius:4px;padding:1px 7px;margin-right:4px;">${k.replace('_',' ')} ${summary[k]}</span>`;
      }).join('');

      const grouped = _ACTION_ORDER.reduce((acc, k) => {
        const grp = gates.filter((g) => g.action_class === k);
        if (!grp.length) return acc;
        const col = _ACTION_COLOR[k] || 'var(--muted)';
        acc += `<li style="padding:4px 0 2px;">
          <div style="font-size:10px;font-weight:800;color:${col};letter-spacing:.06em;margin-bottom:3px;">${k.replace(/_/g,' ')}</div>
          <ul style="margin:0;padding:0 0 0 10px;list-style:disc;">` +
          grp.map((g) => `<li style="padding:2px 0;">
            <span class="small mono" style="color:var(--muted)">${esc(g.source)}</span>
            <div class="small" style="color:var(--text);line-height:1.35;">${esc((g.excerpt||'').slice(0,120))}</div>
          </li>`).join('') +
          `</ul></li>`;
        return acc;
      }, '');

      $('autonomy-gates').innerHTML = `<div style="margin-bottom:8px;">${chips}</div><ul>${grouped}</ul>`;
    }

    // Verifications
    const verifs = (data.recent_verifications || []).slice(0, 8);
    if (!verifs.length) {
      $('autonomy-verifs').innerHTML = '<div class="small">no verifications found</div>';
    } else {
      $('autonomy-verifs').innerHTML = '<ul>' + verifs.map((v) => {
        const vcol = _verdictColor(v.verdict);
        const ts = v.timestamp ? timeAgo(v.timestamp) : '';
        return `<li style="padding:5px 0;">
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="font-size:10px;font-weight:700;color:${vcol};min-width:52px;">${esc(v.verdict)}</span>
            <span class="small mono" style="color:var(--gold-dim);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(v.topic)}</span>
            <span class="small" style="color:var(--muted);white-space:nowrap;">${esc(ts)}</span>
          </div>
          ${v.summary ? `<div class="small" style="color:var(--muted);margin-top:1px;line-height:1.35;">${esc(v.summary.slice(0,100))}</div>` : ''}
        </li>`;
      }).join('') + '</ul>';
    }
  }

  let _autonomyLoaded = false;

  window.loadAutonomy = async function loadAutonomy() {
    const data = await fetchJson('/api/autonomy/overview');
    renderAutonomy(data);
    _autonomyLoaded = true;
  };

  function _confColor(c) {
    if (c >= 0.7) return 'var(--green)';
    if (c >= 0.4) return 'var(--yellow)';
    return 'var(--muted)';
  }

  function renderInvestigations(data) {
    const el = $('autonomy-investigations');
    if (!data || data.error) { el.innerHTML = unavail(data?.error || 'failed'); return; }
    const invs = data.investigations || [];
    if (!invs.length) {
      el.innerHTML = '<div class="small" style="color:var(--green)">No AUTO_REVIEW gates to investigate.</div>';
      return;
    }

    const _RISK_COLOR = { low: 'var(--green)', medium: 'var(--yellow)', high: 'var(--red)' };

    el.innerHTML = invs.map((inv) => {
      const conf = (inv.confidence * 100).toFixed(0);
      const confCol = _confColor(inv.confidence);
      const evidenceRows = (inv.evidence || []).map((e) =>
        `<tr><td style="color:var(--gold-dim);padding:1px 8px 1px 0;white-space:nowrap;">${esc(e.label||e.type)}</td>` +
        `<td class="small mono" style="color:var(--muted);">${esc(String(e.content??'').slice(0,140))}</td></tr>`
      ).join('');

      const actionRows = (inv.actions || []).map((a) => {
        const riskCol = _RISK_COLOR[a.risk] || 'var(--muted)';
        const btnId = `btn-${a.action_id}`;
        const outId = `out-${a.action_id}`;
        const needsApproval = a.requires_approval;
        const btnLabel = a.host_required && !a.command.startsWith('python3 /app/') ? 'Copy' : (needsApproval ? 'Run (requires approval)' : 'Run');
        const btnAction = a.host_required && !a.command.startsWith('python3 /app/')
          ? `navigator.clipboard.writeText(${JSON.stringify(a.command)}).then(()=>{$('${btnId}').textContent='Copied!'});`
          : `runAction(${JSON.stringify(a.action_id)}, ${needsApproval}, '${outId}', '${btnId}')`;
        return `<div style="margin:4px 0;padding:6px 8px;background:var(--surface-2);border-radius:4px;border-left:3px solid ${riskCol};">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px;">
            <span style="font-size:10px;font-weight:700;color:${riskCol};min-width:36px;">${esc(a.risk.toUpperCase())}</span>
            <span style="font-size:11px;color:var(--text);flex:1;">${esc(a.label)}</span>
            ${a.host_required && !a.command.startsWith('python3 /app/') ? '<span style="font-size:9px;color:var(--muted);margin-right:4px;">HOST</span>' : ''}
            <button id="${btnId}" onclick="${btnAction}" style="font-size:10px;padding:2px 8px;border-radius:3px;border:1px solid var(--border-2);background:var(--surface-3);color:var(--muted);cursor:pointer;">${btnLabel}</button>
          </div>
          <code class="small mono" style="color:var(--muted);display:block;overflow-x:auto;white-space:pre;">${esc(a.command)}</code>
          <div id="${outId}" style="display:none;margin-top:4px;padding:4px 6px;background:#0a0a0a;border-radius:3px;font-size:10px;font-family:monospace;color:var(--green);white-space:pre-wrap;max-height:120px;overflow-y:auto;"></div>
        </div>`;
      }).join('');

      return `<div style="border:1px solid var(--border);border-radius:6px;padding:10px 14px;margin-bottom:12px;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
          <span style="font-size:10px;font-weight:700;color:var(--blue);">AUTO_REVIEW</span>
          <span class="small mono" style="color:var(--muted);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(inv.gate_source)}</span>
          <span style="font-size:11px;font-weight:700;color:${confCol};">${conf}%</span>
        </div>
        <div style="font-size:12px;color:var(--text);margin-bottom:4px;">${esc(inv.root_cause_hypothesis)}</div>
        <div class="small" style="color:var(--muted);margin-bottom:6px;line-height:1.4;">${esc((inv.gate_excerpt||'').slice(0,140))}</div>
        ${evidenceRows ? `<table style="width:100%;border-collapse:collapse;margin-bottom:8px;">${evidenceRows}</table>` : ''}
        <div style="font-size:11px;font-weight:700;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.06em;">Action Plan</div>
        ${actionRows || '<div class="small" style="color:var(--muted)">No actions defined.</div>'}
      </div>`;
    }).join('');
  }

  async function runAction(action_id, requires_approval, outId, btnId) {
    const out = $(outId);
    const btn = $(btnId);
    if (requires_approval) {
      const confirmed = confirm(`This action requires approval.\n\nAction ID: ${action_id}\n\nProceed?`);
      if (!confirmed) return;
    }
    btn.textContent = 'Running…';
    btn.disabled = true;
    out.style.display = 'block';
    out.textContent = 'executing…';
    try {
      const res = await fetch('/api/autonomy/execute_action', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({action_id, approved: true}),
      });
      const data = await res.json();
      const statusCol = data.status === 'success' ? 'var(--green)' : data.status === 'host_required' ? 'var(--yellow)' : 'var(--red)';
      out.style.color = statusCol;
      let txt = `status: ${data.status}`;
      if (data.stdout) txt += `\n--- stdout ---\n${data.stdout}`;
      if (data.stderr) txt += `\n--- stderr ---\n${data.stderr}`;
      if (data.returncode != null) txt += `\nreturncode: ${data.returncode}  (${data.duration_sec}s)`;
      out.textContent = txt;
      btn.textContent = data.status === 'success' ? 'Done ✓' : data.status;
    } catch(e) {
      out.textContent = `fetch error: ${e}`;
      btn.textContent = 'Error';
    }
  }

  window.loadInvestigations = async function loadInvestigations() {
    $('autonomy-investigations').innerHTML = '<div class="small">investigating…</div>';
    const data = await fetchJson('/api/autonomy/investigations');
    renderInvestigations(data);
  };

  // ── Incoming Message Context Cards ────────────────────────────────────────

  function _ctxEsc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _ctxFactGroup(heading, byType, borderColor) {
    var keys = Object.keys(byType || {}).sort();
    if (!keys.length) return '';
    var rows = keys.map(function(ft) {
      var items = (byType[ft] || []).map(function(f) {
        var conf = (f.confidence * 100).toFixed(0);
        var excerpt = f.source_excerpt ? '<div class="small mono" style="color:var(--muted);font-size:9px;margin-top:1px;">' + _ctxEsc(f.source_excerpt.slice(0, 100)) + '</div>' : '';
        return '<div style="padding:2px 0;border-bottom:1px solid var(--border);">'
          + '<span style="font-size:11px;color:var(--text);">' + _ctxEsc(f.fact_value) + '</span>'
          + '<span style="font-size:9px;color:var(--muted);margin-left:6px;">' + conf + '%</span>'
          + excerpt + '</div>';
      }).join('');
      return '<div style="margin-bottom:6px;">'
        + '<div style="font-size:9px;font-weight:700;color:var(--gold-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px;">' + _ctxEsc(ft.replace(/_/g,' ')) + '</div>'
        + items + '</div>';
    }).join('');
    return '<div style="border-left:3px solid ' + borderColor + ';padding:6px 10px;margin-bottom:8px;border-radius:0 4px 4px 0;">'
      + '<div style="font-size:10px;font-weight:700;color:' + borderColor + ';margin-bottom:5px;text-transform:uppercase;letter-spacing:.5px;">' + _ctxEsc(heading) + '</div>'
      + rows + '</div>';
  }

  function renderContextCard(data) {
    var el = document.getElementById('ctx-card-result');
    if (!data) { el.innerHTML = '<div class="small" style="color:var(--red)">Failed to load context card.</div>'; return; }

    if (data.status === 'no_handle') {
      el.innerHTML = '<div class="small" style="color:var(--muted)">' + _ctxEsc(data.message) + '</div>';
      return;
    }

    var masked = _ctxEsc(data.contact_masked || '');

    if (data.status === 'no_profile') {
      el.innerHTML = '<div style="padding:10px;border:1px solid var(--border);border-radius:6px;">'
        + '<div style="font-size:11px;color:var(--muted);margin-bottom:4px;">No profile found for <span class="mono">' + masked + '</span></div>'
        + '<div style="font-size:11px;color:var(--text);">' + _ctxEsc(data.suggested_next_action) + '</div>'
        + (data.recent_replies && data.recent_replies.length ? '<div class="small" style="color:var(--muted);margin-top:6px;">' + data.recent_replies.length + ' reply receipt(s) on file.</div>' : '')
        + '</div>';
      return;
    }

    var p = data.profile || {};
    var rtColor = ({'client':'#60a5fa','vendor':'#a78bfa','builder':'#34d399','trade_partner':'#fbbf24','internal_team':'#94a3b8','personal_work_related':'#f472b6'})[p.relationship_type] || 'var(--muted)';
    var conf = ((data.confidence || 0) * 100).toFixed(0);

    var systemsHtml = (p.systems_or_topics || []).length
      ? '<div class="small" style="color:var(--muted);margin-top:3px;">systems: ' + _ctxEsc((p.systems_or_topics || []).slice(0,5).join(', ')) + '</div>' : '';
    var openReqsHtml = (p.open_requests || []).length
      ? '<div class="small" style="color:var(--yellow);margin-top:3px;">open: ' + _ctxEsc((p.open_requests || []).slice(0,3).join(' · ')) + '</div>' : '';
    var projHtml = (p.project_refs || []).length
      ? '<div class="small" style="color:var(--muted);margin-top:3px;">projects: ' + _ctxEsc((p.project_refs || []).slice(0,3).join(', ')) + '</div>' : '';

    var acceptedHtml = _ctxFactGroup('Verified facts', data.accepted_facts, 'var(--green)');
    var pendingHtml  = _ctxFactGroup('Unverified (pending)', data.unverified_facts, 'var(--yellow)');

    var repliesHtml = '';
    if (data.recent_replies && data.recent_replies.length) {
      repliesHtml = '<div style="margin-bottom:8px;">'
        + '<div style="font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;">Recent replies</div>'
        + data.recent_replies.map(function(r) {
            var ts = (r.ts || '').slice(0, 16).replace('T', ' ');
            return '<div class="small mono" style="color:var(--muted);border-bottom:1px solid var(--border);padding:2px 0;">'
              + ts + ' · ' + _ctxEsc(r.phone_last4 || '') + ' · ' + (r.dry_run ? 'dry-run' : (r.success ? '✓ sent' : '✗ failed'))
              + '</div>';
          }).join('')
        + '</div>';
    }

    // Active rules hint badge
    var activeRulesHtml = '';
    if (data.active_rules_applied && data.active_rules_applied.length) {
      activeRulesHtml = '<div style="margin-bottom:8px;">'
        + '<div style="font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;">Active Rules Applied</div>'
        + data.active_rules_applied.map(function(r) {
            return '<div style="font-size:10px;padding:3px 6px;margin-bottom:3px;background:var(--surface-2);border-radius:4px;border-left:2px solid #22c55e;">'
              + '<span style="color:#22c55e;font-family:monospace;">' + _ctxEsc(r.rule_id) + '</span>'
              + ' <span style="color:var(--muted);">·</span> '
              + _ctxEsc(r.summary)
              + '</div>';
          }).join('')
        + '</div>';
    }

    var ctxHandle = _ctxEsc(data.contact_masked || '');
    var draftHtml = '<div style="border:1px solid var(--border);border-radius:4px;padding:8px;background:var(--surface-2);margin-bottom:8px;">'
      + '<div style="font-size:10px;font-weight:700;color:var(--gold-dim);margin-bottom:4px;text-transform:uppercase;letter-spacing:.5px;">Draft Reply</div>'
      + '<div style="font-size:11px;color:var(--text);white-space:pre-wrap;">' + _ctxEsc(data.draft_reply || '') + '</div>'
      + '<div style="margin-top:6px;display:flex;gap:6px;align-items:center;">'
      + '<button disabled style="font-size:9px;padding:2px 10px;border-radius:3px;border:1px solid var(--border-2);background:transparent;color:var(--muted);cursor:not-allowed;" title="Auto-send disabled">✉ Send (disabled)</button>'
      + '</div></div>'

      // Suggest Reply section
      + '<div id="ctx-suggest-box" style="border:1px solid var(--border);border-radius:4px;padding:8px;background:var(--surface-2);margin-bottom:8px;">'
      + '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">'
      + '<span style="font-size:10px;font-weight:700;color:var(--blue);text-transform:uppercase;letter-spacing:.5px;">Suggest Reply</span>'
      + '<button id="ctx-suggest-btn" onclick="window._suggestReply()" style="font-size:9px;padding:2px 10px;border-radius:3px;border:1px solid #3b82f644;background:#3b82f611;color:#60a5fa;cursor:pointer;">✨ Generate</button>'
      + '</div>'
      + '<input id="ctx-suggest-msg" type="text" placeholder="Paste incoming message (optional)…" style="width:100%;box-sizing:border-box;font-size:11px;padding:4px 6px;border:1px solid var(--border-2);border-radius:3px;background:var(--surface);color:var(--text);margin-bottom:6px;">'
      + '<div id="ctx-suggest-result" style="display:none;">'
      + '<textarea id="ctx-suggest-draft" rows="3" style="width:100%;box-sizing:border-box;font-size:11px;padding:4px 6px;border:1px solid var(--border-2);border-radius:3px;background:var(--surface);color:var(--text);resize:vertical;margin-bottom:4px;"></textarea>'
      + '<div style="display:flex;gap:6px;align-items:center;">'
      + '<button onclick="window._copySuggestedReply()" style="font-size:9px;padding:2px 10px;border-radius:3px;border:1px solid var(--border-2);background:transparent;color:var(--muted);cursor:pointer;">⎘ Copy</button>'
      + '<span id="ctx-suggest-meta" style="font-size:9px;color:var(--muted);"></span>'
      + '</div></div>'
      + '</div>';

    // Store handle on window so _suggestReply can read it
    window._ctxCurrentHandle = data.contact_masked || '';

    el.innerHTML = '<div style="border:1px solid var(--border);border-radius:6px;padding:12px;">'
      + '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">'
      + '<span style="font-size:10px;font-weight:700;color:' + rtColor + ';">' + _ctxEsc((p.relationship_type||'').replace(/_/g,' ').toUpperCase()) + '</span>'
      + '<span class="small mono" style="color:var(--muted);">' + masked + '</span>'
      + '<span style="font-size:10px;color:var(--muted);margin-left:auto;">' + conf + '%</span>'
      + '</div>'
      + (p.summary ? '<div class="small" style="color:var(--text);margin-bottom:6px;">' + _ctxEsc(p.summary) + '</div>' : '')
      + systemsHtml + openReqsHtml + projHtml
      + '<div style="font-size:11px;background:var(--surface-2);border-radius:4px;padding:5px 8px;margin:8px 0;border-left:3px solid var(--blue);">'
      + '<span style="font-size:9px;font-weight:700;color:var(--blue);text-transform:uppercase;letter-spacing:.5px;">Suggested action</span>'
      + '<div style="margin-top:2px;color:var(--text);">' + _ctxEsc(data.suggested_next_action) + '</div></div>'
      + acceptedHtml + pendingHtml
      + repliesHtml + activeRulesHtml + draftHtml
      + '</div>';
  }

  window._suggestReply = async function() {
    var btn     = document.getElementById('ctx-suggest-btn');
    var msgEl   = document.getElementById('ctx-suggest-msg');
    var resultEl = document.getElementById('ctx-suggest-result');
    var draftEl = document.getElementById('ctx-suggest-draft');
    var metaEl  = document.getElementById('ctx-suggest-meta');
    if (!btn || !draftEl) return;

    var handle = window._ctxCurrentHandle || '';
    var msg    = msgEl ? msgEl.value.trim() : '';

    btn.disabled = true;
    btn.textContent = '⏳ Generating…';
    if (resultEl) resultEl.style.display = 'none';

    try {
      var resp = await fetch('/api/reply/suggest', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({contact_handle: handle, message_text: msg}),
      });
      var data = await resp.json();
      console.log('[suggest] result', data);

      if (data.status === 'ok' && data.draft) {
        draftEl.value = data.draft;
        if (metaEl) {
          var conf = Math.round((data.confidence || 0) * 100);
          var ruleNames = (data.applied_rules || []).map(function(r) { return r.rule_id; }).join(', ');
          metaEl.textContent = conf + '% confidence' + (ruleNames ? ' · rules: ' + ruleNames : '');
        }
        if (resultEl) resultEl.style.display = '';
      } else {
        alert('Suggest failed: ' + (data.error || JSON.stringify(data)));
      }
    } catch (err) {
      console.error('[suggest] error', err);
      alert('Suggest error: ' + err);
    } finally {
      btn.disabled = false;
      btn.textContent = '✨ Generate';
    }
  };

  window._copySuggestedReply = function() {
    var draftEl = document.getElementById('ctx-suggest-draft');
    if (!draftEl || !draftEl.value) return;
    navigator.clipboard.writeText(draftEl.value).then(function() {
      var btn = document.querySelector('#ctx-suggest-box button[onclick*="_copySuggestedReply"]');
      if (btn) { btn.textContent = '✓ Copied'; setTimeout(function() { btn.textContent = '⎘ Copy'; }, 1500); }
    });
  };

  window.loadContextCard = async function() {
    var input = document.getElementById('ctx-thread-input');
    var raw = (input ? input.value : '').trim();
    if (!raw) return;
    var el = document.getElementById('ctx-card-result');
    el.innerHTML = '<div class="small" style="color:var(--muted)">loading…</div>';

    var param = raw.includes(';') || raw.includes('iMessage') || raw.startsWith('any;')
      ? 'thread_guid=' + encodeURIComponent(raw)
      : 'contact_handle=' + encodeURIComponent(raw);

    var data = await fetchJson('/api/x-intake/context-card?' + param);
    renderContextCard(data);
  };

  // ── Follow-up engine ──────────────────────────────────────────────────────

  window.loadFollowUps = async function loadFollowUps() {
    const el = $('xi-follow-ups');
    if (el) el.innerHTML = '<div class="unavailable">loading…</div>';
    // Use relationship-aware thresholds (no threshold_hours override in production)
    const data = await fetchJson('/api/x-intake/follow-ups?limit=20');
    renderFollowUps(data);
    const navBadge = document.getElementById('nav-fu-count');
    if (navBadge && data && data.count > 0) {
      navBadge.textContent = data.count;
      navBadge.classList.remove('hidden');
    }
  };

  const _FU_PRIORITY_COLOR = {
    urgent: 'var(--red)',
    high:   '#f97316',   // orange
    medium: 'var(--yellow)',
    low:    'var(--muted)',
    review: '#94a3b8',   // slate
    ignore: 'var(--muted)',
  };

  function renderFollowUps(data) {
    const el    = $('xi-follow-ups');
    const badge = $('xi-fu-count');
    if (!el) return;

    if (!data || data.status !== 'ok') {
      el.innerHTML = '<div class="unavailable">unavailable</div>';
      return;
    }

    const items = data.follow_ups || [];
    if (badge) badge.textContent = items.length ? `(${items.length})` : '';

    if (!items.length) {
      el.innerHTML = '<div class="small" style="color:var(--green)">✓ All inbound messages have responses.</div>';
      return;
    }

    el.innerHTML = items.map((item) => {
      const p         = item.profile || {};
      const rt        = item.relationship_type || p.relationship_type || 'unknown';
      const rtLabel   = rt.replace(/_/g, ' ').toUpperCase();
      const rtColor   = (_XI_RT_COLORS[rt] || 'var(--muted)');
      const priority  = item.priority || 'review';
      const priColor  = _FU_PRIORITY_COLOR[priority] || 'var(--muted)';
      const isUrgHigh = priority === 'urgent' || priority === 'high';

      const elapsed   = item.elapsed_hours >= 24
        ? `${(item.elapsed_hours / 24).toFixed(1)}d`
        : `${item.elapsed_hours}h`;
      const overdue   = item.overdue_by_hours >= 24
        ? `${(item.overdue_by_hours / 24).toFixed(1)}d overdue`
        : `${item.overdue_by_hours}h overdue`;

      const systems   = (p.systems_or_topics || []).slice(0, 3).join(', ');
      const draftConf = item.confidence ? ` · ${(item.confidence * 100).toFixed(0)}%` : '';
      const qBadge    = item.draft_quality_status === 'pass'
        ? '<span style="color:var(--green);font-size:8px;">✓ clean</span>'
        : item.draft_quality_status === 'fallback'
        ? '<span style="color:var(--yellow);font-size:8px;">~ fallback</span>'
        : '';

      // Urgent/high items get a stronger left border and background tint
      const cardStyle = isUrgHigh
        ? `border:1px solid ${priColor};border-left:3px solid ${priColor};border-radius:5px;padding:7px 10px;margin-bottom:7px;background:rgba(255,255,255,.02);`
        : `border:1px solid var(--border);border-radius:5px;padding:7px 10px;margin-bottom:7px;`;

      return `<div style="${cardStyle}">
  <div style="display:flex;align-items:center;gap:7px;margin-bottom:3px;flex-wrap:wrap;">
    <span style="font-size:9px;font-weight:700;color:${priColor};text-transform:uppercase;letter-spacing:.4px;">${esc(priority)}</span>
    <span style="font-size:9px;font-weight:700;color:${rtColor};">${esc(rtLabel)}</span>
    <span class="mono" style="font-size:9px;color:var(--muted);">${esc(item.contact_masked || '')}</span>
    <span style="font-size:9px;color:var(--muted);margin-left:auto;">${esc(elapsed)} ago</span>
  </div>
  <div style="font-size:9px;color:${priColor};font-weight:600;margin-bottom:3px;">⏱ ${esc(overdue)}
    <span style="font-weight:400;color:var(--muted);">(threshold: ${item.threshold_hours_used}h)</span>
  </div>
  ${systems ? `<div style="font-size:9px;color:var(--muted);margin-bottom:2px;">systems: ${esc(systems)}</div>` : ''}
  ${item.suggested_next_action ? `<div style="font-size:10px;color:var(--blue);border-left:2px solid var(--blue);padding-left:5px;margin-bottom:4px;">${esc(item.suggested_next_action.slice(0, 90))}</div>` : ''}
  ${item.draft_reply ? `<details style="margin-bottom:4px;"><summary style="font-size:9px;color:var(--muted);cursor:pointer;">draft reply ${draftConf} ${qBadge} ▸</summary>
    <div style="font-size:10px;color:var(--text);margin-top:3px;padding:4px 7px;background:var(--surface-2);border-radius:3px;white-space:pre-wrap;">${esc(item.draft_reply.slice(0, 300))}</div>
  </details>` : ''}
  <button onclick="document.getElementById('ctx-thread-input').value='${esc(item.contact_masked)}';switchTab('xintake');setTimeout(loadContextCard,50);"
    style="font-size:9px;padding:1px 8px;border-radius:3px;border:1px solid var(--border-2);background:transparent;color:var(--muted);cursor:pointer;">
    view context →
  </button>
</div>`;
    }).join('');
  }

  // ── Follow-up header alert ──────────────────────────────────────────────────

  function _updateFollowUpAlert(data) {
    const el = $('fu-header-alert');
    const tx = $('fu-alert-text');
    if (!el || !tx) return;
    if (!data || !data.total) {
      el.classList.add('hidden');
      return;
    }
    const n = data.total;
    let html = `⚠️ ${n} follow-up${n !== 1 ? 's' : ''} needed`;
    if (data.urgent > 0) {
      html += ` · <span style="color:var(--red);font-weight:700;">${data.urgent} urgent</span>`;
    } else if (data.high > 0) {
      html += ` · <span style="color:#f97316;">${data.high} high</span>`;
    }
    tx.innerHTML = html;
    el.classList.remove('hidden');
  }

  window.goToFollowUps = function goToFollowUps() {
    switchTab('xintake');
    setTimeout(() => {
      const card = $('xi-fu-card');
      if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 150);
  };

  async function _pollFollowUpAlert() {
    try {
      const data = await fetchJson('/api/x-intake/follow-up-count');
      _updateFollowUpAlert(data);
    } catch (_) { /* silent — never break the dashboard */ }
  }

  _pollFollowUpAlert();
  setInterval(_pollFollowUpAlert, 30_000);

  // ── Self-Improvement Rules ──────────────────────────────────────────────────

  window.loadSelfImprovement = async function loadSelfImprovement() {
    const _esc = function(s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {
        return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
      });
    };
    const rulesEl = document.getElementById('si-rules');
    const countEl = document.getElementById('si-count');
    const badgeEl = document.getElementById('si-badge');
    const navCount = document.getElementById('nav-si-count');

    if (rulesEl) rulesEl.innerHTML = '<div class="unavailable">loading…</div>';

    let data;
    try {
      const resp = await fetch('/api/self-improvement/promoted-rules');
      data = await resp.json();
    } catch (err) {
      if (rulesEl) rulesEl.innerHTML = '<div class="unavailable">Failed to load rules.</div>';
      return;
    }

    const rules = data.rules || [];
    const proposed = rules.filter(function(r) { return r.status === 'proposed'; });

    if (badgeEl) {
      badgeEl.textContent = data.updated_at ? ('updated ' + data.updated_at.slice(0, 16).replace('T', ' ') + ' UTC') : 'unknown';
    }
    if (countEl) {
      countEl.textContent = rules.length + ' rule' + (rules.length !== 1 ? 's' : '');
    }
    if (navCount) {
      if (proposed.length > 0) {
        navCount.textContent = proposed.length;
        navCount.classList.remove('hidden');
      } else {
        navCount.classList.add('hidden');
      }
    }

    if (!rulesEl) return;

    if (rules.length === 0) {
      rulesEl.innerHTML = '<div class="unavailable">No rules yet. Run: <code>python3 scripts/promote_self_improvement_cards.py --apply</code></div>';
      return;
    }

    const RISK_COLORS = { low: '#22c55e', medium: '#f59e0b', high: '#ef4444' };
    const STATUS_STYLES = {
      approved: 'background:#22c55e22;border:1px solid #22c55e44;color:#22c55e;',
      rejected: 'background:#ef444422;border:1px solid #ef444444;color:#ef4444;',
      proposed: 'background:var(--surface-2);border:1px solid var(--border-2);color:var(--muted);',
    };
    const REC_STYLES = {
      approve: 'background:#22c55e22;border:1px solid #22c55e66;color:#22c55e;',
      review:  'background:#f59e0b22;border:1px solid #f59e0b66;color:#f59e0b;',
      ignore:  'background:#94a3b822;border:1px solid #94a3b844;color:#94a3b8;',
    };

    // Sort by impact_score descending (highest impact first), proposed before others
    const sorted = rules.slice().sort(function(a, b) {
      const statusOrder = { proposed: 0, approved: 1, rejected: 2 };
      const sa = statusOrder[a.status] ?? 1;
      const sb = statusOrder[b.status] ?? 1;
      if (sa !== sb) return sa - sb;
      return (b.impact_score || 0) - (a.impact_score || 0);
    });

    rulesEl.innerHTML = sorted.map(function(r) {
      const riskColor  = RISK_COLORS[r.risk_level] || '#94a3b8';
      const statusSty  = STATUS_STYLES[r.status] || STATUS_STYLES.proposed;
      const riskBadge  = '<span style="display:inline-block;padding:2px 8px;border-radius:100px;font-size:10px;font-weight:700;background:' + riskColor + '22;color:' + riskColor + ';border:1px solid ' + riskColor + '44;">' + (r.risk_level || 'unknown').toUpperCase() + '</span>';
      const statusLabel = r.status === 'approved' ? 'Active rule' : r.status === 'rejected' ? 'Rejected' : r.status || 'proposed';
      const statusBadge = '<span style="display:inline-block;padding:2px 8px;border-radius:100px;font-size:10px;font-weight:700;' + statusSty + '">' + statusLabel + '</span>';

      // Impact + recommendation section
      var impactHtml = '';
      if (r.impact_score != null) {
        const impactPct  = Math.round((r.impact_score || 0) * 100);
        const confPct    = Math.round((r.confidence_score || 0) * 100);
        const rec        = r.recommendation || '';
        const recSty     = REC_STYLES[rec] || REC_STYLES.review;
        const recLabel   = rec ? rec.toUpperCase() : '';
        const recBadge   = rec ? ('<span style="display:inline-block;padding:2px 8px;border-radius:100px;font-size:10px;font-weight:700;' + recSty + '">&#x1F4A1; ' + recLabel + '</span>') : '';
        const eventsLabel = r.impact_events != null ? ('would have touched ' + r.impact_events + ' event' + (r.impact_events !== 1 ? 's' : '')) : '';
        const barColor   = impactPct >= 70 ? '#22c55e' : impactPct >= 40 ? '#f59e0b' : '#94a3b8';
        impactHtml = '<div style="margin-top:8px;padding:8px;background:var(--surface-2);border-radius:6px;border:1px solid var(--border);">'
          + '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px;">'
          + recBadge
          + (eventsLabel ? '<span style="font-size:10px;color:var(--muted);">' + _esc(eventsLabel) + '</span>' : '')
          + '</div>'
          + '<div style="display:flex;gap:16px;align-items:center;margin-bottom:4px;">'
          + '<div style="flex:1;">'
          + '<div style="font-size:10px;color:var(--muted);margin-bottom:2px;">Impact</div>'
          + '<div style="height:6px;background:var(--border);border-radius:3px;overflow:hidden;">'
          + '<div style="height:100%;width:' + impactPct + '%;background:' + barColor + ';border-radius:3px;"></div></div>'
          + '<div style="font-size:10px;color:var(--muted);margin-top:2px;">' + impactPct + '%</div>'
          + '</div>'
          + '<div style="flex:1;">'
          + '<div style="font-size:10px;color:var(--muted);margin-bottom:2px;">Confidence</div>'
          + '<div style="height:6px;background:var(--border);border-radius:3px;overflow:hidden;">'
          + '<div style="height:100%;width:' + confPct + '%;background:#818cf8;border-radius:3px;"></div></div>'
          + '<div style="font-size:10px;color:var(--muted);margin-top:2px;">' + confPct + '%</div>'
          + '</div>'
          + '</div>'
          + (r.recommendation_reason ? '<div style="font-size:10px;color:var(--muted);font-style:italic;">' + _esc(r.recommendation_reason) + '</div>' : '')
          + '</div>';
      }

      let actionHtml = '';
      if (r.status === 'proposed') {
        const safeId = (r.rule_id || '').replace(/'/g, '');
        actionHtml = '<div style="display:flex;gap:8px;margin-top:8px;">'
          + '<button onclick="window.approveRule(\'' + safeId + '\')" style="padding:4px 12px;font-size:11px;background:#22c55e22;border:1px solid #22c55e44;color:#22c55e;border-radius:4px;cursor:pointer;">Approve</button>'
          + '<button onclick="window.rejectRule(\'' + safeId + '\')" style="padding:4px 12px;font-size:11px;background:#ef444422;border:1px solid #ef444444;color:#ef4444;border-radius:4px;cursor:pointer;">Reject</button>'
          + '</div>';
      } else if (r.status === 'rejected' && r.rejected_reason) {
        actionHtml = '<div style="font-size:11px;color:var(--muted);margin-top:4px;">Reason: ' + _esc(r.rejected_reason) + '</div>';
      } else if (r.status === 'approved') {
        const approvedBy = r.approved_by ? (' by ' + _esc(r.approved_by)) : '';
        const approvedAt = r.approved_at ? (' · ' + r.approved_at.slice(0, 10)) : '';
        actionHtml = '<div style="font-size:11px;color:#22c55e;margin-top:4px;">Approved' + approvedBy + approvedAt + '</div>';
      }

      return '<div style="border-bottom:1px solid var(--border);padding:12px 0;">'
        + '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px;">'
        + '<span style="font-size:11px;font-family:monospace;color:var(--muted);">' + _esc(r.rule_id || '') + '</span>'
        + riskBadge + statusBadge
        + '<span style="font-size:10px;color:var(--muted);margin-left:auto;">' + (r.card_count || 0) + ' card' + (r.card_count !== 1 ? 's' : '') + '</span>'
        + '</div>'
        + '<div style="font-size:13px;font-weight:600;margin-bottom:4px;">' + _esc(r.summary || '') + '</div>'
        + '<div style="font-size:11px;color:var(--muted);margin-bottom:2px;"><strong>Source:</strong> ' + _esc(r.source_card || '') + '</div>'
        + '<div style="font-size:11px;color:var(--muted);margin-bottom:4px;">' + _esc(r.proposed_behavior || '') + '</div>'
        + impactHtml
        + actionHtml
        + '</div>';
    }).join('');
  };

  window.approveRule = async function(ruleId) {
    console.log('[SI] approveRule clicked', ruleId);
    if (!confirm('Approve rule ' + ruleId + '?\n\nApproved rules influence system behavior immediately.')) return;
    try {
      const resp = await fetch('/api/self-improvement/promoted-rules/' + encodeURIComponent(ruleId) + '/approve', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({approved_by: 'matt'}),
      });
      const data = await resp.json();
      console.log('[SI] approve result', data);
      if (data.status === 'ok') {
        await window.loadSelfImprovement();
      } else {
        alert('Approve failed: ' + (data.detail || JSON.stringify(data)));
      }
    } catch (err) {
      console.error('[SI] approve error', err);
      alert('Failed to approve rule: ' + err);
    }
  };

  window.rejectRule = async function(ruleId) {
    console.log('[SI] rejectRule clicked', ruleId);
    const reason = prompt('Reason for rejecting ' + ruleId + ' (optional):') || '';
    try {
      const resp = await fetch('/api/self-improvement/promoted-rules/' + encodeURIComponent(ruleId) + '/reject', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({reason: reason}),
      });
      const data = await resp.json();
      console.log('[SI] reject result', data);
      if (data.status === 'ok') {
        await window.loadSelfImprovement();
      } else {
        alert('Reject failed: ' + (data.detail || JSON.stringify(data)));
      }
    } catch (err) {
      console.error('[SI] reject error', err);
      alert('Failed to reject rule: ' + err);
    }
  };

  // ── Reply Suggestion Inbox ──────────────────────────────────────────────────

  const PRIORITY_STYLE = {
    urgent: 'background:#ef444422;border:1px solid #ef444444;color:#ef4444;',
    high:   'background:#f59e0b22;border:1px solid #f59e0b44;color:#f59e0b;',
    medium: 'background:#3b82f622;border:1px solid #3b82f644;color:#3b82f6;',
    low:    'background:var(--surface-2);border:1px solid var(--border-2);color:var(--muted);',
    review: 'background:var(--surface-2);border:1px solid var(--border-2);color:var(--muted);',
  };
  const QUALITY_STYLE = {
    pass:    'background:#22c55e22;border:1px solid #22c55e44;color:#22c55e;',
    warn:    'background:#f59e0b22;border:1px solid #f59e0b44;color:#f59e0b;',
    blocked: 'background:#ef444422;border:1px solid #ef444444;color:#ef4444;',
  };

  function _riCardHtml(s, idx) {
    const priStyle   = PRIORITY_STYLE[s.follow_up_priority] || PRIORITY_STYLE.review;
    const qualStyle  = QUALITY_STYLE[s.draft_quality_status] || QUALITY_STYLE.pass;
    const systems    = (s.systems_or_topics || []).slice(0, 4).join(', ');
    const rulesHtml  = (s.active_rules_applied || []).map(r =>
      `<span style="display:inline-block;margin:2px 4px 2px 0;padding:1px 8px;border-radius:3px;font-size:10px;background:#22c55e18;border:1px solid #22c55e33;color:#22c55e;">${esc(r.summary)}</span>`
    ).join('') || '<span style="color:var(--muted);font-size:11px;">none</span>';
    const reasons    = (s.draft_quality_reasons || []).length
      ? `<div style="margin-top:6px;font-size:11px;color:var(--muted);">Quality notes: ${esc(s.draft_quality_reasons.join('; '))}</div>`
      : '';
    const overdue    = s.overdue_by_hours > 0 ? ` — <span style="color:#f59e0b;">${s.overdue_by_hours}h overdue</span>` : '';

    return `
<div class="card" id="ri-card-${idx}" style="margin-bottom:16px;border-left:4px solid var(--border-2);">
  <!-- Header row -->
  <div style="display:flex;align-items:flex-start;gap:10px;flex-wrap:wrap;margin-bottom:10px;">
    <div style="flex:1;min-width:0;">
      <span style="font-weight:600;font-size:13px;">${esc(s.display_name || s.contact_masked)}</span>
      <span style="font-size:11px;color:var(--muted);margin-left:6px;">${esc(s.contact_masked)}</span>
      <div style="margin-top:3px;font-size:11px;color:var(--muted);">
        ${esc(s.relationship_type.replace(/_/g,' '))}${systems ? ' &mdash; ' + esc(systems) : ''}${overdue}
      </div>
    </div>
    <span style="padding:2px 10px;border-radius:100px;font-size:11px;font-weight:700;${priStyle}">${esc(s.follow_up_priority)}</span>
  </div>

  <!-- Incoming message -->
  ${s.last_message ? `<div style="margin-bottom:10px;padding:8px 12px;background:var(--surface-2);border-radius:6px;border-left:3px solid var(--border-2);font-size:12px;color:var(--muted);">"${esc(s.last_message)}"</div>` : ''}

  <!-- Suggested reply textarea -->
  <div style="margin-bottom:8px;">
    <label style="font-size:11px;color:var(--muted);display:block;margin-bottom:4px;">Suggested reply</label>
    <textarea id="ri-draft-${idx}" rows="3"
      style="width:100%;box-sizing:border-box;padding:8px 10px;background:var(--surface-2);border:1px solid var(--border-2);border-radius:6px;color:var(--text);font-size:12px;font-family:inherit;resize:vertical;"
      >${esc(s.suggested_reply)}</textarea>
  </div>

  <!-- Confidence + quality -->
  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px;font-size:11px;">
    <span>Confidence: <strong>${Math.round((s.confidence||0)*100)}%</strong></span>
    <span style="padding:1px 8px;border-radius:3px;${qualStyle}">${esc(s.draft_quality_status || 'pass')}</span>
    ${reasons}
  </div>

  <!-- Active rules -->
  <div style="margin-bottom:12px;">
    <div style="font-size:11px;color:var(--muted);margin-bottom:4px;">Active rules applied:</div>
    ${rulesHtml}
  </div>

  <!-- Action buttons -->
  <div style="display:flex;gap:8px;flex-wrap:wrap;">
    <button class="btn"
      onclick="window._riRegenerate(${idx}, ${s.queue_item_id || 'null'})"
      style="font-size:11px;padding:4px 12px;">
      Regenerate
    </button>
    <button class="btn"
      onclick="window._riCopy(${idx})"
      style="font-size:11px;padding:4px 12px;">
      Copy
    </button>
    <button class="btn"
      onclick="window._riApprove(${idx}, '${esc(s.action_id)}', '${esc(s.contact_masked)}', ${s.confidence||0}, '${esc(s.draft_quality_status||'pass')}')"
      style="font-size:11px;padding:4px 12px;background:#22c55e22;border-color:#22c55e44;color:#22c55e;">
      Approve Draft
    </button>
    <span id="ri-status-${idx}" style="font-size:11px;color:var(--muted);align-self:center;"></span>
  </div>

  ${s.suggested_next_action ? `<div style="margin-top:10px;font-size:11px;color:var(--muted);">Next action: ${esc(s.suggested_next_action)}</div>` : ''}
</div>`;
  }

  window.loadReplyInbox = async function loadReplyInbox() {
    const cardsEl = document.getElementById('ri-cards');
    const badgeEl = document.getElementById('ri-badge');
    const navCount = document.getElementById('nav-ri-count');
    if (cardsEl) cardsEl.innerHTML = '<div class="unavailable">loading…</div>';

    let data;
    try {
      const resp = await fetch('/api/reply/suggestions/pending', { cache: 'no-store' });
      data = await resp.json();
    } catch (err) {
      if (cardsEl) cardsEl.innerHTML = '<div class="unavailable">Failed to load reply suggestions.</div>';
      return;
    }

    const suggestions = data.suggestions || [];
    const count = data.count || 0;

    if (badgeEl) badgeEl.textContent = count + ' pending';

    if (navCount) {
      if (count > 0) { navCount.textContent = count; navCount.classList.remove('hidden'); }
      else { navCount.classList.add('hidden'); }
    }

    if (!cardsEl) return;

    if (suggestions.length === 0) {
      cardsEl.innerHTML = '<div class="unavailable">No pending reply suggestions.</div>';
      return;
    }

    // Store suggestions for button handlers
    window._riSuggestions = suggestions;
    cardsEl.innerHTML = suggestions.map((s, i) => _riCardHtml(s, i)).join('');
  };

  window._riCopy = function(idx) {
    const ta = document.getElementById('ri-draft-' + idx);
    if (!ta) return;
    navigator.clipboard.writeText(ta.value).then(() => {
      const st = document.getElementById('ri-status-' + idx);
      if (st) { st.textContent = 'Copied!'; setTimeout(() => { st.textContent = ''; }, 2000); }
    }).catch(() => {
      const st = document.getElementById('ri-status-' + idx);
      if (st) st.textContent = 'Copy failed';
    });
  };

  window._riRegenerate = async function(idx, queueItemId) {
    const ta = document.getElementById('ri-draft-' + idx);
    const st = document.getElementById('ri-status-' + idx);
    if (st) st.textContent = 'Regenerating…';
    try {
      const resp = await fetch('/api/reply/regenerate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ queue_item_id: queueItemId, message_text: '' }),
      });
      const data = await resp.json();
      if (data.status === 'ok' && data.draft && ta) {
        ta.value = data.draft;
        if (st) { st.textContent = `Regenerated (${Math.round((data.confidence||0)*100)}%)`; setTimeout(() => { st.textContent = ''; }, 3000); }
      } else if (data.status === 'error') {
        if (st) st.textContent = 'Regenerate failed: ' + (data.error || 'unknown');
      } else {
        // Ollama unavailable or no queue item — show message without alarming
        if (st) { st.textContent = 'Not available (Ollama offline or no queue item)'; setTimeout(() => { st.textContent = ''; }, 3000); }
      }
    } catch (err) {
      if (st) st.textContent = 'Error: ' + String(err).slice(0, 60);
    }
  };

  window._riApprove = async function(idx, actionId, contactMasked, confidence, qualityStatus) {
    const ta = document.getElementById('ri-draft-' + idx);
    const st = document.getElementById('ri-status-' + idx);
    if (!ta || !ta.value.trim()) {
      if (st) st.textContent = 'Draft is empty — cannot approve.';
      return;
    }
    const finalReply = ta.value.trim();
    // The original draft from the suggestions list
    const orig = (window._riSuggestions || [])[idx];
    const origDraft = orig ? (orig.suggested_reply || '') : '';
    const edited = finalReply !== origDraft;

    if (st) st.textContent = 'Approving…';
    try {
      const resp = await fetch('/api/x-intake/approve-reply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action_id:            actionId,
          approved:             true,
          draft_reply:          origDraft,
          edited_reply:         edited ? finalReply : '',
          contact_masked:       contactMasked,
          reasoning:            'Approved from reply inbox',
          confidence:           confidence,
          draft_quality_status: qualityStatus,
        }),
      });
      const data = await resp.json();
      if (data.status === 'ok') {
        const card = document.getElementById('ri-card-' + idx);
        if (card) {
          card.style.opacity = '0.5';
          card.style.pointerEvents = 'none';
        }
        if (st) st.textContent = `Approved (dry-run) — approval_id ${data.approval_id}`;
      } else if (data.status === 'blocked') {
        if (st) st.textContent = 'Blocked: ' + (data.draft_quality_reasons || []).join('; ');
      } else {
        if (st) st.textContent = 'Approval failed: ' + (data.error || data.detail || JSON.stringify(data));
      }
    } catch (err) {
      if (st) st.textContent = 'Error: ' + String(err).slice(0, 60);
    }
  };

  // ── Vault Tab ──────────────────────────────────────────────────────────────

  let _vaultActiveCat = '';

  function _vaultPolicyClass(policy) {
    if (policy === 'high_risk')   return 'vault-policy-high';
    if (policy === 'low_risk')    return 'vault-policy-low';
    return 'vault-policy-medium';
  }

  function _vaultRelTime(ts) {
    if (!ts) return '—';
    const d = new Date(ts);
    const diff = Date.now() - d.getTime();
    const mins = Math.round(diff / 60000);
    if (mins < 60)   return `${mins}m ago`;
    if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
    return `${Math.round(mins / 1440)}d ago`;
  }

  function renderVault(data) {
    const status = document.getElementById('vault-status');
    const wrap   = document.getElementById('vault-table-wrap');
    if (!status || !wrap) return;

    if (data.status === 'unavailable') {
      status.textContent = '⚠ Vault DB not found. Run: python3 scripts/vault_set_secret.py --init';
      wrap.innerHTML = '';
      return;
    }

    const secrets = (data.secrets || []).filter(s =>
      !_vaultActiveCat || s.category === _vaultActiveCat
    );
    status.textContent = `${secrets.length} secret${secrets.length === 1 ? '' : 's'}${_vaultActiveCat ? ' in ' + _vaultActiveCat : ''}`;

    if (!secrets.length) {
      wrap.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:12px 0;">No secrets found.</div>';
      return;
    }

    const rows = secrets.map(s => `
      <tr>
        <td style="font-weight:500;font-size:12px;">${s.name}</td>
        <td><span class="vault-cat-pill">${s.category}</span></td>
        <td class="vault-fp">${s.sha256_fingerprint}</td>
        <td class="${_vaultPolicyClass(s.access_policy)}" style="font-size:11px;">${s.access_policy.replace('_risk','')}</td>
        <td style="color:var(--muted);font-size:11px;">${_vaultRelTime(s.last_accessed_at)}</td>
        <td style="color:var(--muted);font-size:11px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${s.notes || ''}</td>
      </tr>`).join('');

    wrap.innerHTML = `
      <table class="vault-table">
        <thead><tr>
          <th>Name</th><th>Category</th><th>Fingerprint (SHA-256 prefix)</th>
          <th>Policy</th><th>Last Access</th><th>Notes</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  window.loadVault = async function() {
    const status = document.getElementById('vault-status');
    if (status) status.textContent = 'Loading…';
    try {
      const resp = await fetch('/api/vault/secrets');
      const data = await resp.json();
      renderVault(data);
    } catch (err) {
      if (status) status.textContent = 'Error loading vault: ' + String(err).slice(0, 60);
    }
  };

  // Wire up category filter buttons
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.vault-cat-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.vault-cat-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        _vaultActiveCat = btn.dataset.cat || '';
        loadVault();
      });
    });
  });

  // Load vault when its tab is activated
  const _origSwitchTab = window.switchTab;
  window.switchTab = function(tab) {
    _origSwitchTab && _origSwitchTab(tab);
    if (tab === 'vault') loadVault();
  };

})();
