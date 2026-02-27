/* Symphony Smart Homes — Mission Control — Dashboard Logic */

const state = { completedSteps: new Set(), totalSteps: 0 };

document.addEventListener('DOMContentLoaded', () => {
  countSteps();
  updateProgress();
  initNavHighlighting();
  initScrollObserver();
});

function countSteps() {
  state.totalSteps = document.querySelectorAll('.step[data-step]').length;
}

function toggleStep(checkEl) {
  const step = checkEl.closest('.step');
  const stepId = step.dataset.step;
  if (state.completedSteps.has(stepId)) {
    state.completedSteps.delete(stepId);
    step.classList.remove('completed');
  } else {
    state.completedSteps.add(stepId);
    step.classList.add('completed');
  }
  updateProgress();
}

function updateProgress() {
  const completed = state.completedSteps.size;
  const total = state.totalSteps;
  const pct = total > 0 ? (completed / total) * 100 : 0;
  const bar = document.getElementById('progressBar');
  const count = document.getElementById('statusCount');
  if (bar) bar.style.width = pct + '%';
  if (count) count.textContent = completed + ' / ' + total + ' STEPS COMPLETE';
}

function copyCmd(btn, cmd) {
  const textarea = document.createElement('textarea');
  textarea.value = cmd;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  let success = false;
  try {
    success = document.execCommand('copy');
  } catch (e) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(cmd).then(() => {
        showCopyFeedback(btn);
        showToast('Copied to clipboard!');
      });
      document.body.removeChild(textarea);
      return;
    }
  }
  document.body.removeChild(textarea);
  if (success) {
    showCopyFeedback(btn);
    showToast('Copied to clipboard!');
  } else {
    showToast('Copy failed — please copy manually');
  }
}

function showCopyFeedback(btn) {
  btn.classList.add('copied');
  const span = btn.querySelector('span');
  const originalText = span ? span.textContent : '';
  if (span) span.textContent = 'Copied!';
  setTimeout(() => {
    btn.classList.remove('copied');
    if (span) span.textContent = originalText;
  }, 1500);
}

let toastTimeout;
function showToast(message) {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => { toast.classList.remove('show'); }, 2000);
}

function togglePanel(panelId) {
  const panel = document.getElementById(panelId);
  if (panel) panel.classList.toggle('open');
}

function openReference(id) {
  const section = document.getElementById('reference');
  if (section) section.scrollIntoView({ behavior: 'smooth' });
  setTimeout(() => {
    const panel = document.getElementById('panel-filemap');
    if (panel && !panel.classList.contains('open')) panel.classList.add('open');
  }, 500);
}

function generateCommand() {
  const hostname = document.getElementById('nodeHostname').value.trim();
  const role = document.getElementById('nodeRole').value;
  const bobIp = document.getElementById('nodeBobIp').value.trim();
  if (!hostname) { showToast('Please enter a hostname'); document.getElementById('nodeHostname').focus(); return; }
  if (!role) { showToast('Please select a role'); document.getElementById('nodeRole').focus(); return; }
  if (!bobIp) { showToast("Please enter Bob's IP address"); document.getElementById('nodeBobIp').focus(); return; }
  const cmd = `bash setup/nodes/provision_node.sh --hostname ${hostname} --role ${role} --bob-ip ${bobIp}`;
  const output = document.getElementById('generatedOutput');
  const cmdEl = document.getElementById('generatedCmd');
  if (cmdEl) cmdEl.textContent = cmd;
  if (output) { output.style.display = 'block'; output.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
  const copyBtn = document.getElementById('copyGeneratedBtn');
  if (copyBtn) { copyBtn.onclick = function() { copyCmd(copyBtn, cmd); }; }
}

function initNavHighlighting() {
  document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', function() {
      document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
      this.classList.add('active');
    });
  });
}

function initScrollObserver() {
  const sections = document.querySelectorAll('.section');
  const links = document.querySelectorAll('.nav-link');
  if (!('IntersectionObserver' in window)) return;
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const id = entry.target.id;
        links.forEach(l => { l.classList.toggle('active', l.getAttribute('data-section') === id); });
      }
    });
  }, { rootMargin: '-20% 0px -60% 0px', threshold: 0 });
  sections.forEach(section => observer.observe(section));
}

document.querySelectorAll('.toggle input').forEach(toggle => {
  toggle.addEventListener('change', function() {
    const label = this.closest('.agent-status-toggle').querySelector('.toggle-label');
    if (label) {
      label.textContent = this.checked ? 'Active' : 'Inactive';
      label.style.color = this.checked ? 'var(--green)' : 'var(--red)';
    }
  });
});