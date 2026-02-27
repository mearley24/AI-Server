/**
 * Mission Control — Deployment Dashboard
 * Handles step completion tracking, clipboard copy, and node provisioner.
 */

'use strict';

// ─── State ────────────────────────────────────────────────────────────────────

const STORAGE_KEY = 'mc_steps_v1';

let completedSteps = new Set(
  JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
);

// ─── Step definitions ─────────────────────────────────────────────────────────

const STEPS = [
  // ── Server Setup ────────────────────────────────────────────────────────────
  {
    id: 1, phase: 'Server Setup', title: 'Clone the repository',
    cmd: 'git clone https://github.com/mearley24/AI-Server.git ~/AI-Server && cd ~/AI-Server',
  },
  {
    id: 2, phase: 'Server Setup', title: 'Install Node.js 20 (via nvm)',
    cmd: 'curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash && source ~/.zshrc && nvm install 20 && nvm use 20',
  },
  {
    id: 3, phase: 'Server Setup', title: 'Install Docker Desktop',
    cmd: 'brew install --cask docker && open /Applications/Docker.app',
  },
  {
    id: 4, phase: 'Server Setup', title: 'Install Tailscale',
    cmd: 'brew install --cask tailscale && open /Applications/Tailscale.app',
  },
  {
    id: 5, phase: 'Server Setup', title: 'Join Tailscale network',
    cmd: 'tailscale up --hostname=ai-server',
  },

  // ── Bob the Conductor ────────────────────────────────────────────────────────
  {
    id: 6, phase: 'Bob the Conductor', title: 'Install Bob dependencies',
    cmd: 'cd ~/AI-Server/voice_receptionist && npm install',
  },
  {
    id: 7, phase: 'Bob the Conductor', title: 'Configure Bob environment',
    cmd: 'cd ~/AI-Server/voice_receptionist && cp .env.example .env && nano .env',
  },
  {
    id: 8, phase: 'Bob the Conductor', title: 'Seed client database',
    cmd: 'cd ~/AI-Server/voice_receptionist && node scripts/seed_clients.js',
  },
  {
    id: 9, phase: 'Bob the Conductor', title: 'Start Bob (Docker)',
    cmd: 'cd ~/AI-Server/voice_receptionist && docker compose up -d && docker compose ps',
  },
  {
    id: 10, phase: 'Bob the Conductor', title: 'Verify Bob health',
    cmd: 'curl http://localhost:3000/health',
  },

  // ── Symphony Concierge ───────────────────────────────────────────────────────
  {
    id: 11, phase: 'Symphony Concierge', title: 'Pull Ollama base model',
    cmd: 'cd ~/AI-Server/client_ai && docker compose up -d && docker exec symphony-concierge-ollama ollama pull llama3',
  },
  {
    id: 12, phase: 'Symphony Concierge', title: 'Build first client model',
    cmd: 'python3 ~/AI-Server/client_ai/client_knowledge_builder.py --client "The Andersons" --dtools-csv /path/to/andersons.csv --templates ~/AI-Server/client_ai/troubleshooting_templates/',
  },
  {
    id: 13, phase: 'Symphony Concierge', title: 'Load model into Ollama',
    cmd: 'docker exec symphony-concierge-ollama ollama create symphony-andersons:v1 -f /tmp/The_Andersons.Modelfile && docker exec symphony-concierge-ollama ollama list',
  },

  // ── Claude Code ──────────────────────────────────────────────────────────────
  {
    id: 14, phase: 'Claude Code', title: 'Install Claude Code',
    cmd: 'bash ~/AI-Server/setup/claude_code/install_claude_code.sh',
  },
  {
    id: 15, phase: 'Claude Code', title: 'Verify Claude Code',
    cmd: 'claude --version && cat ~/.claude/openclaw_claude_code_tool.json | head -5',
  },

  // ── Nginx & TLS ──────────────────────────────────────────────────────────────
  {
    id: 16, phase: 'Nginx & TLS', title: 'Install Certbot',
    cmd: 'brew install certbot',
  },
  {
    id: 17, phase: 'Nginx & TLS', title: 'Obtain TLS certificate',
    cmd: 'sudo certbot certonly --standalone -d bob.symphonysmarthomes.com',
  },
  {
    id: 18, phase: 'Nginx & TLS', title: 'Configure Twilio webhook',
    cmd: 'echo "Set Twilio webhook to: https://bob.symphonysmarthomes.com/incoming-call"',
  },

  // ── Go Live ──────────────────────────────────────────────────────────────────
  {
    id: 19, phase: 'Go Live', title: 'Full smoke test — call Bob',
    cmd: 'twilio api:core:calls:create --from +13035550100 --to +1YOUR_TEST_NUMBER --url https://bob.symphonysmarthomes.com/incoming-call',
  },
];

// ─── Render ───────────────────────────────────────────────────────────────────

function renderSteps() {
  const container = document.getElementById('steps-container');
  container.innerHTML = '';

  // Group by phase
  const phases = {};
  for (const step of STEPS) {
    if (!phases[step.phase]) phases[step.phase] = [];
    phases[step.phase].push(step);
  }

  for (const [phaseName, steps] of Object.entries(phases)) {
    const phaseEl = document.createElement('div');
    phaseEl.classList.add('phase');

    const phaseHeader = document.createElement('h2');
    phaseHeader.classList.add('phase-title');
    phaseHeader.textContent = phaseName;
    phaseEl.appendChild(phaseHeader);

    for (const step of steps) {
      const done = completedSteps.has(step.id);
      const card = document.createElement('div');
      card.classList.add('step-card');
      if (done) card.classList.add('step-done');
      card.dataset.stepId = step.id;

      card.innerHTML = `
        <div class="step-header">
          <label class="step-check-wrap">
            <input type="checkbox" class="step-check" data-id="${step.id}" ${done ? 'checked' : ''} />
            <span class="step-num">${step.id}</span>
            <span class="step-title">${step.title}</span>
          </label>
        </div>
        <div class="step-cmd-wrap">
          <code class="step-cmd">${escHtml(step.cmd)}</code>
          <button class="copy-btn" data-cmd="${escAttr(step.cmd)}" title="Copy command">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
            </svg>
          </button>
        </div>
      `;
      phaseEl.appendChild(card);
    }

    container.appendChild(phaseEl);
  }

  updateProgress();
}

function updateProgress() {
  const total   = STEPS.length;
  const done    = completedSteps.size;
  const pct     = Math.round((done / total) * 100);

  document.getElementById('progress-count').textContent = `${done} / ${total} steps`;
  document.getElementById('progress-bar').style.width   = `${pct}%`;
  document.getElementById('progress-pct').textContent   = `${pct}%`;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function escAttr(str) {
  return str.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ─── Event delegation ─────────────────────────────────────────────────────────

document.getElementById('steps-container').addEventListener('click', (e) => {
  // Checkbox toggle
  const cb = e.target.closest('.step-check');
  if (cb) {
    const id = parseInt(cb.dataset.id, 10);
    if (cb.checked) completedSteps.add(id); else completedSteps.delete(id);
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...completedSteps]));
    renderSteps();
    return;
  }

  // Copy button
  const copyBtn = e.target.closest('.copy-btn');
  if (copyBtn) {
    navigator.clipboard.writeText(copyBtn.dataset.cmd).then(() => {
      copyBtn.classList.add('copied');
      setTimeout(() => copyBtn.classList.remove('copied'), 1500);
    });
  }
});

// ─── Node provisioner ─────────────────────────────────────────────────────────

document.getElementById('gen-cmd-btn').addEventListener('click', () => {
  const name = document.getElementById('node-client-name').value.trim();
  const key  = document.getElementById('node-ts-key').value.trim();
  const out  = document.getElementById('provision-cmd-output');

  if (!name || !key) {
    out.textContent = '⚠ Please enter both a client name and a Tailscale key.';
    return;
  }

  out.textContent = `bash ~/AI-Server/client_ai/provision_client_node.sh --client "${name}" --tailscale-key ${key}`;
});

document.getElementById('copy-provision-btn').addEventListener('click', () => {
  const text = document.getElementById('provision-cmd-output').textContent;
  if (!text || text.startsWith('⚠')) return;
  navigator.clipboard.writeText(text);
  document.getElementById('copy-provision-btn').textContent = 'Copied!';
  setTimeout(() => { document.getElementById('copy-provision-btn').textContent = 'Copy'; }, 1500);
});

// ─── Init ─────────────────────────────────────────────────────────────────────

renderSteps();
