const STARTED_PREF = 'onboarding_local_llm_started';
const COMPLETED_PREF = 'onboarding_local_llm_completed';

let active = false;
let initialized = false;

async function getPref(key) {
  try {
    const res = await fetch(`/api/prefs/${encodeURIComponent(key)}`, { credentials: 'same-origin' });
    if (!res.ok) return null;
    return (await res.json()).value;
  } catch (_) {
    return null;
  }
}

async function setPref(key, value) {
  try {
    await fetch(`/api/prefs/${encodeURIComponent(key)}`, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value }),
    });
  } catch (_) { /* onboarding state is non-critical */ }
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitFor(selector, visible = false) {
  for (let i = 0; i < 40; i++) {
    const el = document.querySelector(selector);
    if (el && (!visible || (el.getClientRects().length && !el.closest('.hidden')))) return el;
    await delay(75);
  }
  return null;
}

function ensureStyles() {
  if (document.getElementById('local-llm-onboarding-styles')) return;
  const style = document.createElement('style');
  style.id = 'local-llm-onboarding-styles';
  style.textContent = `
    #tour-tooltip.local-llm-tour{max-width:320px;padding:14px 16px;border-radius:8px;
      border:1px solid var(--border);background:var(--bg);color:var(--fg);
      box-shadow:0 12px 36px rgba(0,0,0,.42);font-family:inherit;font-size:.8rem;
      line-height:1.55;position:fixed;z-index:10001;opacity:0;transform:translateY(4px);
      transition:opacity .18s ease,transform .18s ease;pointer-events:auto}
    #tour-tooltip.local-llm-tour.tour-fade-in{opacity:1;transform:translateY(0)}
    #tour-tooltip.local-llm-tour .tour-kicker{color:var(--accent,var(--red));font-size:.68rem;
      font-weight:700;text-transform:uppercase;margin-bottom:5px}
    #tour-tooltip.local-llm-tour .tour-text{margin-bottom:12px;color:color-mix(in srgb,var(--fg) 82%,transparent)}
    #tour-tooltip.local-llm-tour .tour-nav{display:flex;align-items:center;justify-content:space-between;gap:8px}
    #tour-tooltip.local-llm-tour button{border:1px solid var(--border);background:transparent;color:var(--fg);
      border-radius:4px;min-width:34px;height:28px;padding:0 9px;font:inherit;cursor:pointer}
    #tour-tooltip.local-llm-tour button:hover{background:color-mix(in srgb,var(--fg) 9%,transparent)}
    #tour-tooltip.local-llm-tour button[disabled]{opacity:.25;pointer-events:none}
    #tour-tooltip.local-llm-tour .tour-pause{border-color:transparent;opacity:.6}
    .internal-test-warning{position:fixed;z-index:9998;top:10px;left:50%;transform:translateX(-50%);
      display:flex;align-items:center;gap:10px;max-width:min(620px,calc(100vw - 24px));padding:8px 10px;
      border:1px solid color-mix(in srgb,var(--red) 55%,var(--border));border-radius:6px;
      background:var(--panel);color:var(--fg);box-shadow:0 8px 24px rgba(0,0,0,.32);font-size:12px}
    .internal-test-warning strong{color:var(--red)}
    .internal-test-warning button{margin-left:auto;border:0;background:transparent;color:var(--fg);
      opacity:.65;cursor:pointer;font-size:16px;line-height:1}
  `;
  document.head.appendChild(style);
}

function showInternalTestWarning() {
  if (document.querySelector('.internal-test-warning')) return;
  ensureStyles();
  const banner = document.createElement('div');
  banner.className = 'internal-test-warning';
  banner.setAttribute('role', 'status');
  banner.innerHTML = '<span><strong>Internal test account:</strong> Admin / Admin. Change this password in Settings &gt; Account after testing.</span><button type="button" aria-label="Dismiss password warning">&times;</button>';
  banner.querySelector('button').addEventListener('click', () => banner.remove());
  document.body.appendChild(banner);
}

function makeHalo(target) {
  const halo = document.createElement('div');
  halo.className = 'tour-halo';
  document.body.appendChild(halo);
  const update = () => {
    const rect = target.getBoundingClientRect();
    halo.style.top = `${rect.top - 4}px`;
    halo.style.left = `${rect.left - 4}px`;
    halo.style.width = `${rect.width + 8}px`;
    halo.style.height = `${rect.height + 8}px`;
  };
  update();
  window.addEventListener('resize', update);
  window.addEventListener('scroll', update, true);
  requestAnimationFrame(() => halo.classList.add('tour-fade-in'));
  return () => {
    window.removeEventListener('resize', update);
    window.removeEventListener('scroll', update, true);
    halo.remove();
  };
}

function positionTooltip(tooltip, target) {
  const rect = target.getBoundingClientRect();
  const width = tooltip.offsetWidth || 320;
  const height = tooltip.offsetHeight || 140;
  const gap = 12;
  let top = rect.bottom + gap;
  let left = rect.left + (rect.width / 2) - (width / 2);
  if (top + height > window.innerHeight - 10) top = rect.top - height - gap;
  if (top < 10) top = 10;
  left = Math.max(10, Math.min(left, window.innerWidth - width - 10));
  tooltip.style.top = `${top}px`;
  tooltip.style.left = `${left}px`;
}

async function runSteps(steps, kicker) {
  ensureStyles();
  window.cancelActiveTour?.();
  document.body.classList.add('tour-active');
  const tooltip = document.createElement('div');
  tooltip.id = 'tour-tooltip';
  tooltip.className = 'local-llm-tour';
  document.body.appendChild(tooltip);
  let clearHalo = () => {};

  const cleanup = () => {
    clearHalo();
    tooltip.remove();
    document.body.classList.remove('tour-active');
  };

  for (let index = 0; index < steps.length;) {
    const step = steps[index];
    clearHalo();
    if (step.before) await step.before();
    await delay(180);
    const target = await waitFor(step.selector, true);
    if (!target) {
      index += 1;
      continue;
    }
    target.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    clearHalo = makeHalo(target);
    tooltip.classList.remove('tour-fade-in');
    tooltip.innerHTML = `
      <div class="tour-kicker">${kicker} ${index + 1} / ${steps.length}</div>
      <div class="tour-text">${step.text}</div>
      <div class="tour-nav">
        <button type="button" data-action="back" aria-label="Previous step" ${index === 0 ? 'disabled' : ''}>&#8592;</button>
        <button type="button" class="tour-pause" data-action="pause">Pause</button>
        <button type="button" data-action="next" aria-label="Next step">${index === steps.length - 1 ? '&#10003;' : '&#8594;'}</button>
      </div>`;
    positionTooltip(tooltip, target);
    requestAnimationFrame(() => tooltip.classList.add('tour-fade-in'));

    const action = await new Promise(resolve => {
      tooltip.onclick = event => {
        const button = event.target.closest('[data-action]');
        if (button && !button.disabled) resolve(button.dataset.action);
      };
    });
    if (action === 'pause') {
      cleanup();
      return 'paused';
    }
    if (action === 'back') index = Math.max(0, index - 1);
    else index += 1;
  }

  cleanup();
  return 'completed';
}

async function openCookbook(tab = 'Search') {
  const modal = document.getElementById('cookbook-modal');
  if (modal?.classList.contains('hidden')) document.getElementById('tool-cookbook-btn')?.click();
  await waitFor('#cookbook-modal .modal-content', true);
  const tabButton = document.querySelector(`#cookbook-modal .cookbook-tab[data-backend="${tab}"]`);
  tabButton?.click();
}

async function openBrain(tab = 'browse') {
  document.getElementById('close-cookbook-modal')?.click();
  const modal = document.getElementById('memory-modal');
  if (modal?.classList.contains('hidden')) document.getElementById('tool-memory-btn')?.click();
  await waitFor('#memory-modal .memory-modal-content', true);
  document.querySelector(`.memory-tab[data-memory-tab="${tab}"]`)?.click();
}

async function runDownloadStage() {
  if (active) return;
  active = true;
  await setPref(STARTED_PREF, true);
  await openCookbook('Search');
  await runSteps([
    {
      selector: '#cookbook-modal .modal-content',
      text: '<b>Welcome to your local AI setup.</b> Cookbook finds a model that fits this Mac, downloads it, and starts it privately on this computer.',
    },
    {
      selector: '#cookbook-dl-repo',
      text: 'Search for a model by name or paste a Hugging Face model URL here. A smaller quantized model is usually the quickest first test.',
      before: () => openCookbook('Search'),
    },
    {
      selector: '#hwfit-list',
      text: 'Use the hardware-fit results to choose a model. Download the recommended quantization and wait for it to finish.',
      before: () => openCookbook('Search'),
    },
    {
      selector: '#cookbook-modal .cookbook-tab[data-backend="Serve"]',
      text: 'Open <b>Serve</b>, select the downloaded model, and start it. This tutorial resumes automatically when Cookbook registers the local endpoint.',
      before: () => openCookbook('Serve'),
    },
  ], 'Local LLM');
  active = false;
}

async function runUsageStage() {
  if (active || await getPref(COMPLETED_PREF) === true) return;
  active = true;
  document.getElementById('close-cookbook-modal')?.click();
  const result = await runSteps([
    {
      selector: '#model-picker-btn',
      text: 'Your served model now appears in the model picker. Cookbook normally selects it automatically; use this control whenever you want to switch models.',
    },
    {
      selector: '#message',
      text: 'Send a simple first request, such as <b>Summarize the three priorities I give you.</b> The selected local model handles the response.',
    },
    {
      selector: '#web-toggle-btn',
      text: '<b>Web Search is an explicit permission.</b> OFF keeps this request local. ON allows the assistant to search the internet for this mode. The switch always shows the current state.',
    },
    {
      selector: '#new-memory-input',
      text: 'Add a durable preference, for example <b>I prefer concise replies with action items first</b>, then press Enter. Memories provide facts and preferences across chats.',
      before: () => openBrain('add'),
    },
    {
      selector: '#new-skill-title',
      text: 'Teach a repeatable procedure as a <b>Skill</b>: give it a title, describe when to use it, write the steps under How, add tags, then choose Add Skill. Matching skills can guide later requests and tasks.',
      before: () => openBrain('add'),
    },
    {
      selector: '#memory-enabled-header-toggle',
      text: 'This switch controls whether relevant memories are included in requests. Turn it off when you want a conversation without saved context.',
      before: () => openBrain('browse'),
    },
    {
      selector: '#auto-memory-toggle',
      text: '<b>Auto-extract memories</b> can suggest useful facts from conversations. Auto-extract skills can draft repeatable procedures; review and approve them before relying on them for future tasks.',
      before: () => openBrain('settings'),
    },
    {
      selector: '#message',
      text: 'Now test recall: ask <b>How should you format responses for me?</b> The model can use the memory you created. Your local LLM onboarding is complete.',
      before: () => document.getElementById('close-memory-modal')?.click(),
    },
  ], 'Use Your LLM');
  if (result === 'completed') {
    await setPref(COMPLETED_PREF, true);
    const url = new URL(window.location.href);
    url.searchParams.delete('onboarding');
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
  }
  active = false;
}

export async function runLocalLlmOnboarding(stage = 'download') {
  if (stage === 'usage') return runUsageStage();
  return runDownloadStage();
}

export async function initLocalLlmOnboarding() {
  if (initialized) return;
  initialized = true;
  window.addEventListener('cookbook:model-serve-registered', () => runUsageStage());

  let status = {};
  try {
    const res = await fetch('/api/auth/status', { credentials: 'same-origin' });
    if (res.ok) status = await res.json();
  } catch (_) { /* normal non-authenticated modes do not auto-onboard */ }
  const requested = new URLSearchParams(window.location.search).get('onboarding') === 'local-llm';
  if (!requested && !status.internal_test_defaults) return;
  if (await getPref(COMPLETED_PREF) === true) return;
  if (status.internal_test_defaults) showInternalTestWarning();

  const started = await getPref(STARTED_PREF) === true;
  if (started) {
    try {
      const res = await fetch('/api/model-endpoints', { credentials: 'same-origin' });
      const endpoints = res.ok ? await res.json() : [];
      const localReady = endpoints.some(ep => ep.is_enabled && ep.endpoint_kind === 'local'
        && ((ep.models || []).length || (ep.pinned_models || []).length));
      if (localReady) return setTimeout(() => runUsageStage(), 700);
    } catch (_) { /* return to Cookbook below */ }
  }
  setTimeout(() => runDownloadStage(), 700);
}

export default { initLocalLlmOnboarding, runLocalLlmOnboarding };
