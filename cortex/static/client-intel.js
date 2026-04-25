'use strict';
(function(){

  // ── Tab wiring for client-intel ──────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function() {
    var orig = window._tabSwitchHook;
    document.querySelectorAll('[data-tab="client-intel"]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        if (!window._ciLoaded) { loadClientIntel(); }
      });
    });
  });

  // ── Helpers ───────────────────────────────────────────────────────────────
  var _RT_COLOR = {
    client: '#60a5fa', vendor: '#a78bfa', builder: '#34d399',
    trade_partner: '#fbbf24', internal_team: '#94a3b8',
    personal_work_related: '#f472b6',
  };

  function esc(s) {
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  async function fetchJson(url) {
    try { const r = await fetch(url); return r.ok ? r.json() : null; }
    catch(e) { return null; }
  }

  // ── Profile renderer ──────────────────────────────────────────────────────
  function renderProfiles(data) {
    var el = document.getElementById('ci-profiles');
    var ct = document.getElementById('ci-profiles-count');
    if (!data || data.error) { el.innerHTML = '<div class="unavailable">unavailable</div>'; return; }
    var profiles = data.profiles || [];
    ct.textContent = profiles.length ? '(' + profiles.length + ')' : '';
    var nav = document.getElementById('nav-ci-count');
    if (profiles.length) { nav.textContent = profiles.length; nav.classList.remove('hidden'); }
    else { nav.classList.add('hidden'); }

    if (!profiles.length) {
      el.innerHTML = '<div class="small" style="color:var(--muted)">No profiles yet. Run: python3 scripts/extract_relationship_profiles.py --apply-approved</div>';
      return;
    }
    el.innerHTML = profiles.map(function(p) {
      var col = _RT_COLOR[p.relationship_type] || 'var(--muted)';
      var sys = (p.systems_or_topics||[]).slice(0,4).join(', ') || '—';
      var proj = (p.project_refs||[]).slice(0,3).join(', ') || '—';
      var conf = (p.confidence * 100).toFixed(0);
      var statusCol = p.status === 'approved' ? 'var(--green)' : p.status === 'archived' ? 'var(--muted)' : 'var(--yellow)';
      var pid = esc(p.profile_id);
      return '<div style="border:1px solid var(--border);border-radius:6px;padding:8px 12px;margin-bottom:8px;">'
        + '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">'
        + '<span style="font-size:10px;font-weight:700;color:' + col + ';">' + esc(p.relationship_type.replace(/_/g,' ').toUpperCase()) + '</span>'
        + '<span class="small mono" style="color:var(--muted);flex:1;">' + esc(p.contact_masked) + '</span>'
        + '<span style="font-size:10px;color:' + statusCol + ';font-weight:700;">' + esc(p.status) + '</span>'
        + '<span style="font-size:10px;color:var(--muted);">' + conf + '%</span>'
        + '<button onclick="toggleProfileDetail(\'' + pid + '\',this)" style="font-size:9px;padding:1px 7px;border-radius:3px;border:1px solid var(--border-2);background:transparent;color:var(--muted);cursor:pointer;">▸ details</button>'
        + '</div>'
        + '<div class="small" style="color:var(--text);margin-bottom:3px;">' + esc(p.summary||'') + '</div>'
        + '<div class="small" style="color:var(--muted);">systems: ' + esc(sys) + '</div>'
        + (proj !== '—' ? '<div class="small" style="color:var(--muted);">projects: ' + esc(proj) + '</div>' : '')
        + '<div id="ci-detail-' + pid + '" style="display:none;margin-top:8px;border-top:1px solid var(--border);padding-top:8px;"></div>'
        + '</div>';
    }).join('');
  }

  // ── Profile detail loader ─────────────────────────────────────────────────
  window.toggleProfileDetail = async function(profileId, btn) {
    var detailEl = document.getElementById('ci-detail-' + profileId);
    if (!detailEl) return;
    if (detailEl.style.display !== 'none') {
      detailEl.style.display = 'none';
      btn.textContent = '▸ details';
      return;
    }
    btn.textContent = '▾ loading…';
    detailEl.style.display = 'block';
    if (detailEl.dataset.loaded) { btn.textContent = '▾ details'; return; }
    var data = await fetchJson('/api/client-intel/profiles/' + profileId);
    if (!data || data.status !== 'ok') {
      detailEl.innerHTML = '<div class="small" style="color:var(--red)">Failed to load detail.</div>';
      btn.textContent = '▸ details';
      return;
    }
    detailEl.innerHTML = renderProfileDetailHtml(data.facts_by_type);
    detailEl.dataset.loaded = '1';
    btn.textContent = '▾ details';
  };

  function renderProfileDetailHtml(factsByType) {
    var types = Object.keys(factsByType || {}).sort();
    if (!types.length) return '<div class="small" style="color:var(--muted)">No proposed facts for this profile.</div>';
    return types.map(function(ftype) {
      var factsHtml = (factsByType[ftype] || []).map(function(f) {
        var conf = (f.confidence * 100).toFixed(0);
        var stateLabel = f.is_accepted ? '<span style="color:var(--green);font-size:9px;">accepted</span>'
                       : f.is_rejected ? '<span style="color:var(--red);font-size:9px;">rejected</span>'
                       : '';
        var ts = f.source_timestamp ? f.source_timestamp.slice(0, 10) : '';
        return '<div style="padding:3px 0 4px;border-bottom:1px solid var(--border);">'
          + '<div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap;">'
          + '<span style="font-size:11px;color:var(--text);flex:1;">' + esc(f.fact_value) + '</span>'
          + stateLabel
          + '<span style="font-size:10px;color:var(--muted);">' + conf + '%</span>'
          + (f.is_accepted === 0 && f.is_rejected === 0
              ? '<button onclick="approveFact(\'' + esc(f.fact_id) + '\',this)" style="font-size:9px;padding:1px 6px;border-radius:3px;border:1px solid var(--green);background:transparent;color:var(--green);cursor:pointer;">✓</button>'
              + '<button onclick="rejectFact(\'' + esc(f.fact_id) + '\',this)" style="font-size:9px;padding:1px 6px;border-radius:3px;border:1px solid var(--red);background:transparent;color:var(--red);cursor:pointer;">✗</button>'
              : '')
          + '</div>'
          + (f.source_excerpt ? '<div class="small mono" style="color:var(--muted);font-size:9px;margin-top:2px;">' + esc(f.source_excerpt.slice(0, 120)) + (ts ? ' <span style="opacity:.6">— ' + esc(ts) + '</span>' : '') + '</div>' : '')
          + '</div>';
      }).join('');
      return '<div style="margin-bottom:8px;">'
        + '<div style="font-size:10px;font-weight:700;color:var(--gold-dim);margin-bottom:3px;text-transform:uppercase;letter-spacing:.5px;">' + esc(ftype.replace(/_/g,' ')) + '</div>'
        + factsHtml
        + '</div>';
    }).join('');
  }

  // ── Facts renderer ────────────────────────────────────────────────────────
  // data comes from ?accepted=all so we can show pending + state summary
  function renderFacts(data) {
    var el = document.getElementById('ci-facts');
    var ct = document.getElementById('ci-facts-count');
    if (!data || data.error) { el.innerHTML = '<div class="unavailable">unavailable</div>'; return; }
    var all = data.facts || [];
    var pending  = all.filter(function(f) { return !f.is_accepted && !f.is_rejected; });
    var accepted = all.filter(function(f) { return f.is_accepted; });
    var rejected = all.filter(function(f) { return f.is_rejected; });

    // Header count: "N pending · M accepted · P rejected"
    var parts = [];
    if (pending.length)  parts.push('<span style="color:var(--yellow)">' + pending.length + ' pending</span>');
    if (accepted.length) parts.push('<span style="color:var(--green)">' + accepted.length + ' accepted</span>');
    if (rejected.length) parts.push('<span style="color:var(--muted)">' + rejected.length + ' rejected</span>');
    ct.innerHTML = parts.length ? '(' + parts.join(' · ') + ')' : '';

    if (!all.length) {
      el.innerHTML = '<div class="small" style="color:var(--muted)">No proposed facts yet. Run extraction script.</div>';
      return;
    }
    // Show pending first, then accepted (dimmed), then rejected (dimmed)
    var rows = pending.concat(accepted, rejected).slice(0, 40);
    el.innerHTML = rows.map(function(f) {
      var conf = (f.confidence * 100).toFixed(0);
      var isPending  = !f.is_accepted && !f.is_rejected;
      var isAccepted = f.is_accepted;
      var opacity    = isPending ? '1' : '0.45';
      var borderCol  = isAccepted ? 'var(--green)' : (f.is_rejected ? 'var(--red)' : 'var(--border-2)');
      return '<div style="border-left:3px solid ' + borderCol + ';padding:4px 8px;margin-bottom:6px;opacity:' + opacity + ';">'
        + '<div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">'
        + '<span style="font-size:10px;font-weight:700;color:var(--gold-dim);">' + esc(f.fact_type) + '</span>'
        + '<span style="font-size:11px;color:var(--text);flex:1;">' + esc(String(f.fact_value).slice(0,80)) + '</span>'
        + '<span style="font-size:10px;color:var(--muted);">' + conf + '%</span>'
        + (isPending
            ? '<button onclick="approveFact(\'' + esc(f.fact_id) + '\',this)" style="font-size:9px;padding:1px 6px;border-radius:3px;border:1px solid var(--green);background:transparent;color:var(--green);cursor:pointer;">✓</button>'
            + '<button onclick="rejectFact(\'' + esc(f.fact_id) + '\',this)" style="font-size:9px;padding:1px 6px;border-radius:3px;border:1px solid var(--red);background:transparent;color:var(--red);cursor:pointer;">✗</button>'
            : '<span style="font-size:9px;color:var(--muted);">' + (isAccepted ? '✓ accepted' : '✗ rejected') + '</span>')
        + '</div>'
        + (f.source_excerpt ? '<div class="small mono" style="color:var(--muted);font-size:9px;">' + esc(f.source_excerpt.slice(0,100)) + '</div>' : '')
        + '</div>';
    }).join('');
    if (all.length > 40) {
      el.innerHTML += '<div class="small" style="color:var(--muted);margin-top:4px;">' + (all.length - 40) + ' more… use API for full list.</div>';
    }
  }

  // ── Fact actions ──────────────────────────────────────────────────────────
  window.approveFact = async function(factId, btn) {
    btn.disabled = true;
    const r = await fetch('/api/client-intel/approve-fact', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({fact_id: factId}),
    });
    const d = await r.json();
    if (d.status === 'ok') { btn.parentElement.parentElement.style.opacity = '0.4'; }
    btn.disabled = false;
  };

  window.rejectFact = async function(factId, btn) {
    btn.disabled = true;
    const r = await fetch('/api/client-intel/reject-fact', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({fact_id: factId}),
    });
    const d = await r.json();
    if (d.status === 'ok') { btn.parentElement.parentElement.remove(); }
    btn.disabled = false;
  };

  // ── Backfill status renderer ──────────────────────────────────────────────
  window.loadBackfillStatus = async function() {
    var el = document.getElementById('ci-backfill-status');
    if (!el) return;
    el.innerHTML = '<div class="small" style="color:var(--muted)">loading…</div>';
    var d = await fetchJson('/api/client-intel/backfill-status');
    if (!d || d.total_indexed === undefined) {
      el.innerHTML = '<div class="unavailable">unavailable — run: python3 scripts/client_intel_backfill.py --apply --limit 1000</div>';
      return;
    }
    var cells = [
      ['Total Indexed', d.total_indexed, 'var(--text)'],
      ['Work', d.work, 'var(--green)'],
      ['Mixed', d.mixed, 'var(--yellow)'],
      ['Personal', d.personal, 'var(--muted)'],
      ['Unknown', d.unknown, 'var(--muted)'],
      ['Reviewed', d.reviewed, 'var(--blue)'],
      ['Approved Profiles', d.approved_profiles, 'var(--cyan)'],
      ['Pending Facts', d.proposed_facts, 'var(--gold)'],
    ];
    var grid = cells.map(function(c) {
      return '<div style="text-align:center;padding:6px 8px;background:var(--surface-2);border:1px solid var(--border);border-radius:6px;">'
        + '<div style="font-size:18px;font-weight:700;color:' + c[2] + ';font-family:var(--mono);">' + c[1] + '</div>'
        + '<div style="font-size:10px;color:var(--muted);margin-top:2px;">' + c[0] + '</div>'
        + '</div>';
    }).join('');
    var lastRun = d.last_run
      ? '<div class="small" style="margin-top:8px;color:var(--muted)">Last run: ' + new Date(d.last_run).toLocaleString() + '</div>'
      : '<div class="small" style="margin-top:8px;color:var(--muted)">No runs yet — run: python3 scripts/client_intel_backfill.py --dry-run --limit 1000</div>';
    el.innerHTML = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:8px;">' + grid + '</div>' + lastRun;
  };

  // ── Load ──────────────────────────────────────────────────────────────────
  window._ciLoaded = false;
  window.loadClientIntel = async function() {
    var badge = document.getElementById('ci-badge');
    badge.textContent = 'loading…';
    const [pd, fd] = await Promise.all([
      fetchJson('/api/client-intel/profiles'),
      fetchJson('/api/client-intel/proposed-facts?accepted=all&limit=200'),
    ]);
    renderProfiles(pd);
    renderFacts(fd);
    loadBackfillStatus();
    badge.textContent = pd ? (pd.count + ' profiles') : 'unavailable';
    window._ciLoaded = true;
  };
})();
