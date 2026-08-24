// First-class Meetings and Knowledge workspaces for OM Automate.
// Provider/model secrets are never requested or rendered here.

const qs = (selector, root = document) => root.querySelector(selector);
const node = (tag, attrs = {}, text = '') => {
  const el = document.createElement(tag);
  Object.entries(attrs).forEach(([key, value]) => {
    if (key === 'class') el.className = value;
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (value !== false && value != null) el.setAttribute(key, value === true ? '' : String(value));
  });
  if (text) el.textContent = text;
  return el;
};

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options });
  let body = null;
  try { body = await response.json(); } catch (_) { body = {}; }
  if (!response.ok) {
    const detail = body.detail || body;
    throw new Error(detail.message || detail.error || `Request failed (${response.status})`);
  }
  return body;
}

function announce(modal, message, error = false) {
  const status = qs('.om-workspace-status', modal);
  status.textContent = message;
  status.dataset.error = error ? 'true' : 'false';
}

function ensureModal() {
  let modal = document.getElementById('om-workspace-modal');
  if (modal) return modal;
  modal = node('div', { id: 'om-workspace-modal', class: 'om-workspace-modal hidden' });
  const dialog = node('section', { class: 'om-workspace-dialog', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'om-workspace-title' });
  const header = node('header', { class: 'om-workspace-header' });
  header.append(node('div', { class: 'om-workspace-heading' }), node('button', { class: 'om-workspace-close', type: 'button', 'aria-label': 'Close workspace', onclick: () => closeModal(modal) }, '×'));
  const status = node('div', { class: 'om-workspace-status', role: 'status', 'aria-live': 'polite' });
  const body = node('div', { class: 'om-workspace-body' });
  dialog.append(header, status, body); modal.append(dialog); document.body.append(modal);
  modal.addEventListener('click', (event) => { if (event.target === modal) closeModal(modal); });
  modal.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeModal(modal); });
  return modal;
}

function closeModal(modal) {
  if (modal.__recorder && modal.__recorder.state !== 'inactive') modal.__recorder.stop();
  modal.classList.add('hidden');
  modal.__returnFocus?.focus();
}

function openShell(kind, subtitle) {
  const modal = ensureModal();
  modal.__returnFocus = document.activeElement;
  modal.classList.remove('hidden');
  const heading = qs('.om-workspace-heading', modal); heading.replaceChildren();
  const title = node('h2', { id: 'om-workspace-title' }, kind);
  heading.append(title, node('p', {}, subtitle));
  qs('.om-workspace-body', modal).replaceChildren(); announce(modal, '');
  qs('.om-workspace-close', modal).focus();
  return modal;
}

function field(label, input) {
  const wrap = node('label', { class: 'om-workspace-field' });
  wrap.append(node('span', {}, label), input); return wrap;
}

function formatTime(ms) {
  const seconds = Math.floor((Number(ms) || 0) / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

async function openWork() {
  const modal = openShell('Work', 'Tasks, projects, commitments, dependencies, and source-linked planning in one durable workspace.');
  const body = qs('.om-workspace-body', modal);
  const toolbar = node('div', { class: 'om-workspace-toolbar' });
  const view = node('select', { 'aria-label': 'Work record type' });
  [['tasks', 'Tasks'], ['projects', 'Projects'], ['commitments', 'Commitments']].forEach(([value, label]) => view.append(node('option', { value }, label)));
  const create = node('button', { type: 'button', class: 'om-primary' }, 'New task');
  const refresh = node('button', { type: 'button' }, 'Refresh'); toolbar.append(view, create, refresh);
  const planning = node('div', { class: 'om-workspace-toolbar', role: 'group', 'aria-label': 'Work planning views' });
  [['Daily focus', '/api/work/planning/focus'], ['Blocked', '/api/work/planning/blocked'], ['Overdue commitments', '/api/work/planning/overdue-commitments'], ['Due reminders', '/api/work/reminders/due'], ['Activity', '/api/work/audit?limit=100']].forEach(([label, path]) => {
    const button = node('button', { type: 'button' }, label);
    button.addEventListener('click', async () => {
      try {
        const data = await api(path); const rows = data.tasks || data.commitments || data.reminders || data.receipts || [];
        detail.replaceChildren(node('h3', {}, label));
        if (!rows.length) detail.append(node('p', { class: 'om-empty' }, 'Nothing in this view.'));
        rows.forEach((item) => {
          const card = node('article', { class: 'om-source-card' });
          const title = item.title || item.message || `${item.operation || 'change'} · ${item.entity_type || 'record'}`;
          const context = item.planning?.reasons?.join(' · ') || item.occurred_at || item.remind_at || item.due_at || '';
          card.append(node('strong', {}, title), node('small', {}, context)); detail.append(card);
        });
      } catch (error) { announce(modal, error.message, true); }
    }); planning.append(button);
  });
  const columns = node('div', { class: 'om-workspace-columns' });
  const list = node('div', { class: 'om-workspace-list' }); const detail = node('div', { class: 'om-workspace-detail' });
  columns.append(list, detail); body.append(toolbar, planning, columns);

  const endpoint = () => `/api/work/${view.value}`;
  async function load() {
    try {
      const data = await api(endpoint() + (view.value === 'tasks' ? '?include_completed=true' : ''));
      const rows = data[view.value] || []; list.replaceChildren();
      if (!rows.length) list.append(node('p', { class: 'om-empty' }, `No ${view.value} yet.`));
      rows.forEach((item) => {
        const row = node('button', { type: 'button', class: 'om-record-row', onclick: () => show(item) });
        row.append(node('strong', {}, item.title), node('span', {}, `${item.status || 'active'}${item.due_at ? ` · due ${new Date(item.due_at).toLocaleString()}` : ''}`)); list.append(row);
      });
    } catch (error) { announce(modal, error.message, true); }
  }
  function showCreate() {
    detail.replaceChildren(); const form = node('form', { class: 'om-workspace-form' });
    const title = node('input', { required: true, maxlength: 500, autocomplete: 'off' });
    const description = node('textarea', { rows: 4, maxlength: 100000 });
    const due = node('input', { type: 'datetime-local' });
    const reminder = node('input', { type: 'datetime-local' });
    const sourceUrl = node('input', { type: 'url', maxlength: 4000, placeholder: 'https://…' });
    form.append(node('h3', {}, `New ${view.value.slice(0, -1)}`), field('Title', title));
    if (view.value !== 'projects') form.append(field('Due', due));
    form.append(field(view.value === 'projects' ? 'Goal' : 'Description', description), field('Source link (optional)', sourceUrl));
    if (view.value !== 'projects') form.append(field('Reminder (optional)', reminder));
    form.append(node('button', { type: 'submit', class: 'om-primary' }, 'Create'));
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const payload = { title: title.value };
      if (view.value === 'projects') { payload.goal = description.value; payload.status = 'active'; }
      else { payload.description = description.value; if (due.value) payload.due_at = new Date(due.value).toISOString(); }
      if (sourceUrl.value) payload.references = [{ type: 'url', url: sourceUrl.value, label: title.value }];
      if (reminder.value && view.value !== 'projects') payload.reminders = [{ remind_at: new Date(reminder.value).toISOString(), message: title.value, channel: 'in_app', status: 'pending' }];
      try { await api(endpoint(), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); announce(modal, `${view.value.slice(0, -1)} created and recorded in the activity audit.`); await load(); showCreate(); }
      catch (error) { announce(modal, error.message, true); }
    });
    detail.append(form); title.focus();
  }
  async function show(item) {
    detail.replaceChildren(); detail.append(node('h3', {}, item.title));
    const meta = node('div', { class: 'om-privacy-card' });
    meta.append(node('strong', {}, item.status || 'active'), node('p', {}, item.description || item.goal || item.desired_outcome || 'No description.'), node('small', {}, `Revision ${item.revision}${item.source_type ? ` · source ${item.source_type}` : ''}`)); detail.append(meta);
    const actions = node('div', { class: 'om-workspace-toolbar' });
    if (view.value === 'tasks' && item.status !== 'completed') {
      const complete = node('button', { type: 'button', class: 'om-primary' }, 'Mark complete'); actions.append(complete);
      complete.addEventListener('click', async () => { try { await api(`${endpoint()}/${encodeURIComponent(item.id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'completed', completed_at: new Date().toISOString(), revision: item.revision }) }); await load(); announce(modal, 'Task marked complete with a revision receipt.'); detail.replaceChildren(); } catch (error) { announce(modal, error.message, true); } });
    }
    const remove = node('button', { type: 'button' }, 'Delete'); actions.append(remove); detail.append(actions);
    remove.addEventListener('click', async () => {
      if (!window.confirm(`Delete “${item.title}”? This exact revision will be recorded.`)) return;
      try { await api(`${endpoint()}/${encodeURIComponent(item.id)}?revision=${item.revision}`, { method: 'DELETE' }); announce(modal, 'Record deleted.'); detail.replaceChildren(); await load(); } catch (error) { announce(modal, error.message, true); }
    });
    if (item.dependencies?.length) detail.append(dashboardCard('Dependencies', item.dependencies, (entry) => entry.title || entry.id));
    if (item.references?.length) detail.append(dashboardCard('Sources and references', item.references, (entry) => entry.title || entry.url || entry.id));
    if (item.reminders?.length) detail.append(dashboardCard('Reminders', item.reminders, (entry) => `${new Date(entry.remind_at).toLocaleString()} · ${entry.message || entry.status}`));
    try {
      const entityType = view.value.slice(0, -1); const history = await api(`/api/work/audit?entity_type=${encodeURIComponent(entityType)}&entity_id=${encodeURIComponent(item.id)}&limit=50`);
      if (history.receipts.length) detail.append(dashboardCard('Status history', history.receipts, (entry) => `${entry.operation} · ${new Date(entry.occurred_at).toLocaleString()}`));
    } catch (_) { /* The record remains usable when history is temporarily unavailable. */ }
  }
  view.addEventListener('change', () => { create.textContent = `New ${view.value.slice(0, -1)}`; detail.replaceChildren(); load(); showCreate(); });
  create.addEventListener('click', showCreate); refresh.addEventListener('click', load); await load(); showCreate();
}

async function openLife() {
  const modal = openShell('Life & Travel', 'User-approved relationship context, personal administration, and proposal-only travel planning.');
  const body = qs('.om-workspace-body', modal); const toolbar = node('div', { class: 'om-workspace-toolbar' });
  const kind = node('select', { 'aria-label': 'Life record type' });
  [['relationship', 'Relationships'], ['admin', 'Personal admin'], ['trip', 'Trips'], ['travel_item', 'Travel items']].forEach(([value, label]) => kind.append(node('option', { value }, label)));
  const create = node('button', { type: 'button', class: 'om-primary' }, 'New relationship'); const refresh = node('button', { type: 'button' }, 'Refresh'); toolbar.append(kind, create, refresh);
  const columns = node('div', { class: 'om-workspace-columns' }); const list = node('div', { class: 'om-workspace-list' }); const detail = node('div', { class: 'om-workspace-detail' }); columns.append(list, detail); body.append(toolbar, columns);
  let trips = [];
  async function load() {
    try {
      const data = await api(`/api/life?kind=${encodeURIComponent(kind.value)}&limit=200`); list.replaceChildren();
      if (!data.records.length) list.append(node('p', { class: 'om-empty' }, 'No records in this category.'));
      data.records.forEach((item) => { const row = node('button', { type: 'button', class: 'om-record-row', onclick: () => show(item) }); row.append(node('strong', {}, item.name || item.title), node('span', {}, item.status || item.follow_up_status || item.category || item.item_type || 'active')); list.append(row); });
      if (kind.value === 'trip') trips = data.records;
    } catch (error) { announce(modal, error.message, true); }
  }
  async function showCreate() {
    detail.replaceChildren(); const form = node('form', { class: 'om-workspace-form' }); const title = node('input', { required: true, maxlength: 500 }); const notes = node('textarea', { rows: 4, maxlength: 20000 });
    form.append(node('h3', {}, `New ${kind.value.replace('_', ' ')}`), field(kind.value === 'relationship' ? 'Name' : 'Title', title));
    let extra = null; let optIn = null;
    if (kind.value === 'relationship') { extra = node('input', { maxlength: 500, placeholder: 'Organisation' }); optIn = node('input', { type: 'checkbox', required: true }); form.append(field('Organisation', extra), field('I approve storing this relationship profile', optIn), field('Notes', notes)); }
    if (kind.value === 'admin') { extra = node('select'); ['renewal','subscription','bill','important_document','warranty','insurance','travel_document','property','vehicle','membership','household_maintenance','recurring_appointment'].forEach(value => extra.append(node('option', { value }, value.replaceAll('_',' ')))); optIn = node('input', { type: 'checkbox' }); form.append(field('Category', extra), field('Financial/sensitive opt-in (required for bills, subscriptions, insurance)', optIn), field('Details', notes)); }
    if (kind.value === 'trip') { extra = node('input', { maxlength: 500, placeholder: 'Destination' }); form.append(field('Destination', extra), field('Notes', notes)); }
    if (kind.value === 'travel_item') { if (!trips.length) { const tripData = await api('/api/life?kind=trip&limit=200'); trips = tripData.records; } extra = node('select'); trips.forEach(trip => extra.append(node('option', { value: trip.id }, trip.title))); const itemType = node('select'); ['flight','accommodation','transfer','reservation','travel_document','calendar_event','packing_item','pre_travel_task','during_travel_briefing','post_travel_expense'].forEach(value => itemType.append(node('option',{value},value.replaceAll('_',' ')))); optIn = itemType; form.append(field('Trip', extra), field('Item type', itemType), field('Details (no payment or booking instructions)', notes)); }
    const submit = node('button', { type: 'submit', class: 'om-primary' }, 'Create locally'); form.append(node('p', { class: 'om-empty' }, 'OM Automate does not purchase, book, pay, or contact anyone from this workspace.'), submit);
    form.addEventListener('submit', async (event) => { event.preventDefault(); const record = {};
      if (kind.value === 'relationship') Object.assign(record, { name: title.value, organization: extra.value, notes: notes.value, user_approved: optIn.checked });
      if (kind.value === 'admin') { const financial = ['bill','subscription','insurance'].includes(extra.value); Object.assign(record, { title: title.value, category: extra.value, details: { notes: notes.value }, status: 'active', sensitive: financial && optIn.checked, financial_opt_in: financial && optIn.checked }); }
      if (kind.value === 'trip') Object.assign(record, { title: title.value, destination: extra.value, notes: notes.value, status: 'planning', origin_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC', destination_timezone: 'UTC' });
      if (kind.value === 'travel_item') Object.assign(record, { title: title.value, trip_id: extra.value, item_type: optIn.value, details: { notes: notes.value }, status: 'planned', sensitive: false });
      try { await api('/api/life', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: kind.value, record }) }); announce(modal, 'Private local record created.'); await load(); await showCreate(); } catch (error) { announce(modal, error.message, true); }
    }); detail.append(form); title.focus();
  }
  function show(item) { detail.replaceChildren(); detail.append(node('h3', {}, item.name || item.title)); const card = node('div', { class: 'om-privacy-card' }); const summary = [item.organization, item.role, item.destination, item.category, item.item_type, item.status].filter(Boolean).join(' · '); card.append(node('strong', {}, summary || item.kind), node('p', {}, item.notes || item.details?.notes || 'No notes.'), node('small', {}, `Private owner record · revision ${item.revision}`)); detail.append(card); const remove = node('button', { type: 'button' }, 'Delete'); detail.append(remove); remove.addEventListener('click', async () => { if (!window.confirm(`Delete “${item.name || item.title}”?`)) return; try { await api(`/api/life/${encodeURIComponent(item.kind)}/${encodeURIComponent(item.id)}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision: item.revision, confirm: true }) }); detail.replaceChildren(); await load(); } catch (error) { announce(modal, error.message, true); } }); }
  kind.addEventListener('change', async () => { create.textContent = `New ${kind.value.replace('_',' ')}`; await load(); await showCreate(); }); create.addEventListener('click', showCreate); refresh.addEventListener('click', load); await load(); await showCreate();
}

async function openIntegrationHealth() {
  const modal = openShell('Integrations', 'Capabilities, permissions, health, and owner privacy state without exposing secrets.'); const body = qs('.om-workspace-body', modal);
  const toolbar = node('div', { class: 'om-workspace-toolbar' }); const refresh = node('button', { type: 'button' }, 'Refresh health'); const configure = node('button', { type: 'button', class: 'om-primary' }, 'Configure integrations'); toolbar.append(refresh, configure); const grid = node('div', { class: 'om-source-grid' }); body.append(toolbar, grid);
  async function load() { try { const [catalog, health] = await Promise.all([api('/api/integration-registry/catalog'), api('/api/integration-registry/health')]); const states = new Map(health.integrations.map(item => [item.id, item])); grid.replaceChildren(); catalog.integrations.forEach(item => { const state = states.get(item.id) || {}; const card = node('article', { class: 'om-source-card' }); card.append(node('strong', {}, item.name), node('span', {}, `${state.status || 'unknown'} · ${item.authentication_method}`), node('small', {}, `Capabilities: ${(item.capabilities || []).join(', ') || 'none'}`), node('small', {}, `Scopes: ${(item.permission_scopes || []).join(', ') || 'none'}`)); if (state.last_error) card.append(node('p', {}, state.last_error)); if (state.recommended_repair) card.append(node('p', {}, state.recommended_repair)); grid.append(card); }); } catch (error) { announce(modal, error.message, true); } }
  refresh.addEventListener('click', load); configure.addEventListener('click', () => { closeModal(modal); window.settingsModule?.open('integrations'); }); await load();
}

async function openMeetings() {
  const modal = openShell('Meetings', 'Record with consent, upload, transcribe locally, and review source-linked outcomes.');
  const body = qs('.om-workspace-body', modal);
  const toolbar = node('div', { class: 'om-workspace-toolbar' });
  const createButton = node('button', { type: 'button', class: 'om-primary' }, 'New meeting');
  const refreshButton = node('button', { type: 'button' }, 'Refresh');
  toolbar.append(createButton, refreshButton);
  const columns = node('div', { class: 'om-workspace-columns' });
  const list = node('div', { class: 'om-workspace-list', 'aria-label': 'Meeting list' });
  const detail = node('div', { class: 'om-workspace-detail' });
  columns.append(list, detail); body.append(toolbar, columns);

  async function loadList() {
    try {
      const data = await api('/api/meetings?limit=100'); list.replaceChildren();
      if (!data.meetings.length) list.append(node('p', { class: 'om-empty' }, 'No meetings yet. Create one, then record or upload media.'));
      data.meetings.forEach((meeting) => {
        const button = node('button', { type: 'button', class: 'om-record-row', onclick: () => showMeeting(meeting.id) });
        button.append(node('strong', {}, meeting.title), node('span', {}, `${meeting.status} · ${meeting.source_type}`)); list.append(button);
      });
    } catch (error) { announce(modal, error.message, true); }
  }

  function showCreate() {
    detail.replaceChildren();
    const form = node('form', { class: 'om-workspace-form' });
    const title = node('input', { required: true, maxlength: 500, autocomplete: 'off' });
    const description = node('textarea', { rows: 3, maxlength: 100000 });
    form.append(node('h3', {}, 'New meeting'), field('Title', title), field('Description', description), node('button', { type: 'submit', class: 'om-primary' }, 'Create meeting'));
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      try {
        const created = await api('/api/meetings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: title.value, description: description.value, source_type: 'manual' }) });
        announce(modal, 'Meeting created. Add media only after confirming attendee consent.'); await loadList(); await showMeeting(created.id);
      } catch (error) { announce(modal, error.message, true); }
    });
    detail.append(form); title.focus();
  }

  async function showMeeting(id) {
    try {
      const meeting = await api(`/api/meetings/${encodeURIComponent(id)}`); detail.replaceChildren();
      const heading = node('div', { class: 'om-detail-heading' });
      heading.append(node('div', {}, meeting.title), node('span', {}, meeting.status)); detail.append(heading);
      const privacy = node('div', { class: 'om-privacy-card' });
      const consent = node('input', { type: 'checkbox', id: 'om-meeting-consent' });
      const consentLabel = node('label', { for: 'om-meeting-consent' }); consentLabel.append(consent, document.createTextNode(' I confirm recording/upload complies with attendee consent and local law.'));
      privacy.append(node('strong', {}, 'Private local processing'), node('p', {}, 'Transcription is post-meeting, not realtime. Media is sent only to this OM Automate server.'), consentLabel); detail.append(privacy);

      const actions = node('div', { class: 'om-workspace-toolbar' });
      const uploadInput = node('input', { type: 'file', accept: 'audio/*,video/*', class: 'om-file-input' });
      const uploadButton = node('button', { type: 'button' }, meeting.media.available ? 'Replace media' : 'Upload media');
      const recordButton = node('button', { type: 'button' }, 'Record microphone');
      const transcribeButton = node('button', { type: 'button', class: 'om-primary' }, 'Transcribe locally');
      actions.append(uploadButton, uploadInput, recordButton, transcribeButton); detail.append(actions);
      uploadButton.addEventListener('click', () => uploadInput.click());
      uploadInput.addEventListener('change', async () => {
        if (!consent.checked) return announce(modal, 'Confirm attendee consent before uploading.', true);
        const file = uploadInput.files[0]; if (!file) return;
        const data = new FormData(); data.append('file', file); data.append('consent_confirmed', 'true'); data.append('replace', meeting.media.available ? 'true' : 'false');
        try { await api(`/api/meetings/${encodeURIComponent(id)}/media`, { method: 'POST', body: data }); announce(modal, 'Media uploaded privately.'); await showMeeting(id); await loadList(); } catch (error) { announce(modal, error.message, true); }
      });
      recordButton.addEventListener('click', async () => {
        if (!consent.checked) return announce(modal, 'Confirm attendee consent before recording.', true);
        if (modal.__recorder && modal.__recorder.state === 'recording') { modal.__recorder.stop(); return; }
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true }); const pieces = [];
          const recorderOptions = MediaRecorder.isTypeSupported('audio/webm') ? { mimeType: 'audio/webm' } : undefined;
          const recorder = new MediaRecorder(stream, recorderOptions); modal.__recorder = recorder;
          recorder.ondataavailable = (event) => { if (event.data.size) pieces.push(event.data); };
          recorder.onstop = async () => {
            stream.getTracks().forEach((track) => track.stop()); recordButton.textContent = 'Record microphone';
            const blob = new Blob(pieces, { type: recorder.mimeType || 'audio/webm' }); const data = new FormData(); data.append('file', blob, 'browser-recording.webm'); data.append('consent_confirmed', 'true'); data.append('replace', meeting.media.available ? 'true' : 'false');
            try { await api(`/api/meetings/${encodeURIComponent(id)}/media`, { method: 'POST', body: data }); announce(modal, 'Recording saved privately.'); await showMeeting(id); await loadList(); } catch (error) { announce(modal, error.message, true); }
          };
          recorder.start(1000); recordButton.textContent = 'Stop and save recording'; announce(modal, 'Recording… Stop when the meeting is complete.');
        } catch (error) { announce(modal, `Microphone unavailable: ${error.message}`, true); }
      });
      transcribeButton.disabled = !meeting.media.available;
      transcribeButton.addEventListener('click', async () => {
        try { await api(`/api/meetings/${encodeURIComponent(id)}/transcription-jobs`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': `ui-${id}-${meeting.transcription.revision + 1}` }, body: JSON.stringify({ model: 'base', timestamp_granularity: 'segment' }) }); announce(modal, 'Transcription queued. You can close this workspace; processing continues locally.'); await showMeeting(id); await loadList(); } catch (error) { announce(modal, error.message, true); }
      });

      if (meeting.segments.length) {
        const transcriptHeading = node('div', { class: 'om-detail-heading' });
        transcriptHeading.append(node('h3', {}, 'Transcript'));
        const analyzeMeeting = node('button', { type: 'button', class: 'om-primary' }, meeting.claims.length ? 'Re-analyze outcomes' : 'Analyze outcomes');
        analyzeMeeting.addEventListener('click', async () => {
          try { await api(`/api/meetings/${encodeURIComponent(id)}/analysis-jobs`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': `analysis-ui-${id}-${meeting.transcription.revision}` }, body: JSON.stringify({ reason: 'User requested source-linked outcome analysis' }) }); announce(modal, 'Meeting analysis queued with transcript-span evidence.'); await showMeeting(id); await loadList(); } catch (error) { announce(modal, error.message, true); }
        });
        const saveKnowledge = node('button', { type: 'button' }, 'Save to knowledge');
        saveKnowledge.addEventListener('click', async () => {
          if (!window.confirm('Save this private transcript to your Knowledge index?')) return;
          try { await api(`/api/meetings/${encodeURIComponent(id)}/knowledge`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true }) }); announce(modal, 'Transcript saved to private Knowledge with timestamps and speaker evidence.'); await showMeeting(id); } catch (error) { announce(modal, error.message, true); }
        });
        transcriptHeading.append(analyzeMeeting, saveKnowledge); detail.append(transcriptHeading);
        const transcript = node('div', { class: 'om-transcript' });
        meeting.segments.forEach((segment) => {
          const row = node('article', { class: 'om-transcript-segment' });
          row.append(node('span', {}, `${formatTime(segment.start_ms)}–${formatTime(segment.end_ms)} · ${segment.speaker_label || 'Unknown speaker'}`), node('p', {}, segment.text));
          const edit = node('button', { type: 'button' }, 'Edit transcript'); row.append(edit);
          edit.addEventListener('click', () => {
            const form = node('form', { class: 'om-workspace-form' }); const text = node('textarea', { rows: 4, maxlength: 100000 }); text.value = segment.text;
            const speaker = node('input', { maxlength: 100, placeholder: 'Speaker label' }); speaker.value = segment.speaker_label || '';
            form.append(field('Transcript text', text), field('Speaker label', speaker), node('button', { type: 'submit', class: 'om-primary' }, 'Save revision'));
            form.addEventListener('submit', async (event) => { event.preventDefault(); try { await api(`/api/meetings/${encodeURIComponent(id)}/segments/${encodeURIComponent(segment.id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: text.value, speaker_label: speaker.value || null, revision: segment.revision }) }); announce(modal, 'Transcript revision saved with the prior text retained in history.'); await showMeeting(id); } catch (error) { announce(modal, error.message, true); } });
            row.replaceChildren(form); text.focus();
          });
          transcript.append(row);
        }); detail.append(transcript);
        if (meeting.speakers?.length) {
          detail.append(node('h3', {}, 'Speaker mapping'));
          const speakerGrid = node('div', { class: 'om-source-grid' });
          meeting.speakers.forEach((entry) => {
            const form = node('form', { class: 'om-source-card' }); const name = node('input', { required: true, maxlength: 255, placeholder: 'Display name', 'aria-label': `Name for ${entry.label}` }); name.value = entry.display_name || '';
            form.append(node('strong', {}, entry.label), name, node('small', {}, entry.user_confirmed ? 'User confirmed' : 'Unconfirmed'), node('button', { type: 'submit' }, 'Map speaker'));
            form.addEventListener('submit', async (event) => { event.preventDefault(); try { await api(`/api/meetings/${encodeURIComponent(id)}/speakers/${encodeURIComponent(entry.label)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ display_name: name.value, confidence: 1 }) }); announce(modal, `Mapped ${entry.label} to ${name.value}.`); await showMeeting(id); } catch (error) { announce(modal, error.message, true); } }); speakerGrid.append(form);
          }); detail.append(speakerGrid);
        }
      }
      if (meeting.claims.length) {
        detail.append(node('h3', {}, 'Source-linked outcomes'));
        meeting.claims.forEach((claim) => {
          const card = node('article', { class: 'om-claim-card' }); card.append(node('strong', {}, `${claim.kind.replaceAll('_', ' ')} · ${claim.fact_state}`), node('p', {}, claim.text));
          const evidence = claim.evidence.map((item) => `${formatTime(item.start_ms)}–${formatTime(item.end_ms)}`).join(', '); card.append(node('small', {}, `Evidence: ${evidence || 'none'}`)); detail.append(card);
          if (claim.approval_state === 'pending') {
            const reviews = node('div', { class: 'om-workspace-toolbar' });
            const positiveLabel = claim.kind === 'decision' ? 'Confirm decision' : 'Approve';
            const approve = node('button', { type: 'button', class: 'om-primary' }, positiveLabel);
            const reject = node('button', { type: 'button' }, 'Reject');
            async function review(decision) {
              if (!window.confirm(`${decision === 'reject' ? 'Reject' : positiveLabel} this exact source-linked claim?`)) return;
              try { await api(`/api/meetings/${encodeURIComponent(id)}/claims/${encodeURIComponent(claim.id)}/review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, confirm: true, revision: claim.revision }) }); announce(modal, decision === 'reject' ? 'Claim rejected.' : 'Claim reviewed and linked action completed.'); await showMeeting(id); await loadList(); } catch (error) { announce(modal, error.message, true); }
            }
            approve.addEventListener('click', () => review(claim.kind === 'decision' ? 'confirm' : 'approve'));
            reject.addEventListener('click', () => review('reject')); reviews.append(approve, reject); card.append(reviews);
          }
        });
      }
    } catch (error) { announce(modal, error.message, true); }
  }
  createButton.addEventListener('click', showCreate); refreshButton.addEventListener('click', loadList); await loadList(); showCreate();
}

async function openKnowledge() {
  const modal = openShell('Knowledge', 'Private, source-grounded search with governed memories and local indexing.');
  const body = qs('.om-workspace-body', modal);
  const searchForm = node('form', { class: 'om-knowledge-search' });
  const query = node('input', { type: 'search', placeholder: 'Search your private knowledge…', maxlength: 2000, 'aria-label': 'Knowledge search query' });
  searchForm.append(query, node('button', { type: 'submit', class: 'om-primary' }, 'Search'));
  const toolbar = node('div', { class: 'om-workspace-toolbar' });
  const upload = node('input', { type: 'file', accept: '.txt,.md,.markdown,.pdf,.docx,.csv,.json,.html,.xml,.yaml,.yml' });
  const refresh = node('button', { type: 'button' }, 'Refresh sources'); const vaultButton = node('button', { type: 'button' }, 'Document vault'); toolbar.append(upload, refresh, vaultButton);
  const results = node('div', { class: 'om-knowledge-results', 'aria-live': 'polite' });
  const sources = node('div', { class: 'om-source-grid' });
  const memoryToolbar = node('div', { class: 'om-workspace-toolbar' }); const newMemory = node('button', { type: 'button', class: 'om-primary' }, 'New memory'); const refreshMemories = node('button', { type: 'button' }, 'Refresh memories'); memoryToolbar.append(newMemory, refreshMemories);
  const memories = node('div', { class: 'om-source-grid' });
  body.append(searchForm, toolbar, results, node('h3', {}, 'Sources'), sources, node('h3', {}, 'Reviewable memory'), memoryToolbar, memories);

  async function loadSources() {
    try {
      const data = await api('/api/knowledge/sources?limit=100'); sources.replaceChildren();
      if (!data.sources.length) sources.append(node('p', { class: 'om-empty' }, 'No indexed sources yet. Upload a supported document or explicitly save a meeting transcript.'));
      data.sources.forEach((source) => {
        const card = node('article', { class: 'om-source-card' });
        card.append(node('strong', {}, source.title), node('span', {}, `${source.type} · ${source.processing_status}`), node('small', {}, `${source.sensitivity} · version ${source.version}`));
        if (['document','pdf','text','markdown','attachment','imported_record'].includes(source.type)) {
          const analyze = node('button', { type: 'button' }, source.metadata?.vault ? 'Review vault record' : 'Analyze for vault'); card.append(analyze);
          analyze.addEventListener('click', async () => { try { const record = source.metadata?.vault ? source : await api(`/api/knowledge/sources/${encodeURIComponent(source.id)}/analyze-vault`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true }) }); await showVaultRecord(record); await loadSources(); } catch (error) { announce(modal, error.message, true); } });
        }
        sources.append(card);
      });
    } catch (error) { announce(modal, error.message, true); }
  }
  async function loadMemories() {
    try {
      const data = await api('/api/knowledge/memories'); memories.replaceChildren();
      if (!data.memories.length) memories.append(node('p', { class: 'om-empty' }, 'No memories. Suggested memories remain inactive until you approve them.'));
      data.memories.forEach((memory) => {
        const card = node('article', { class: 'om-source-card' }); card.append(node('strong', {}, `${memory.category} · ${memory.status}`), node('p', {}, memory.text), node('small', {}, `${memory.sensitive ? 'Sensitive' : 'Normal visibility'}${memory.expires_at ? ` · expires ${new Date(memory.expires_at).toLocaleString()}` : ''}`));
        const actions = node('div', { class: 'om-workspace-toolbar' });
        if (memory.status === 'suggested') {
          const approve = node('button', { type: 'button', class: 'om-primary' }, 'Approve'); const reject = node('button', { type: 'button' }, 'Reject'); actions.append(approve, reject);
          const setStatus = async (status) => { try { await api(`/api/knowledge/memories/${encodeURIComponent(memory.id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status, revision: memory.revision }) }); announce(modal, `Memory ${status}.`); await loadMemories(); } catch (error) { announce(modal, error.message, true); } };
          approve.addEventListener('click', () => setStatus('approved')); reject.addEventListener('click', () => setStatus('rejected'));
        }
        const edit = node('button', { type: 'button' }, 'Edit'); const remove = node('button', { type: 'button' }, 'Delete'); actions.append(edit, remove); card.append(actions);
        edit.addEventListener('click', () => { const form = node('form', { class: 'om-workspace-form' }); const text = node('textarea', { required: true, rows: 4, maxlength: 20000 }); text.value = memory.text; const sensitive = node('input', { type: 'checkbox' }); sensitive.checked = memory.sensitive; form.append(field('Memory', text), field('Sensitive', sensitive), node('button', { type: 'submit', class: 'om-primary' }, 'Save revision')); form.addEventListener('submit', async (event) => { event.preventDefault(); try { await api(`/api/knowledge/memories/${encodeURIComponent(memory.id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: text.value, sensitive: sensitive.checked, revision: memory.revision }) }); await loadMemories(); } catch (error) { announce(modal, error.message, true); } }); card.replaceChildren(form); text.focus(); });
        remove.addEventListener('click', async () => { if (!window.confirm('Delete this memory permanently from the active knowledge store?')) return; try { await api(`/api/knowledge/memories/${encodeURIComponent(memory.id)}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision: memory.revision, confirm: true }) }); await loadMemories(); } catch (error) { announce(modal, error.message, true); } }); memories.append(card);
      });
    } catch (error) { announce(modal, error.message, true); }
  }
  function showNewMemory() {
    memories.replaceChildren(); const form = node('form', { class: 'om-workspace-form' }); const category = node('select'); ['preferences','people','organisations','projects','responsibilities','goals','routines','decisions','commitments','important_dates','assets','properties','travel','professional_context','personal_administration'].forEach(value => category.append(node('option', { value }, value.replaceAll('_',' ')))); const text = node('textarea', { required: true, rows: 5, maxlength: 20000 }); const sensitive = node('input', { type: 'checkbox' }); const expires = node('input', { type: 'datetime-local' }); form.append(node('h4', {}, 'New suggested memory'), field('Category', category), field('Memory', text), field('Sensitive', sensitive), field('Expires', expires), node('button', { type: 'submit', class: 'om-primary' }, 'Save suggestion')); form.addEventListener('submit', async (event) => { event.preventDefault(); try { await api('/api/knowledge/memories', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ category: category.value, text: text.value, status: 'suggested', sensitive: sensitive.checked, expires_at: expires.value ? new Date(expires.value).toISOString() : null }) }); announce(modal, 'Memory saved as a reviewable suggestion.'); await loadMemories(); } catch (error) { announce(modal, error.message, true); } }); memories.append(form); text.focus();
  }
  async function showVaultRecord(source) {
    const vault = source.metadata?.vault || {}; results.replaceChildren();
    const form = node('form', { class: 'om-workspace-form' }); const classification = node('select'); ['identity','financial','insurance','property','vehicle','legal','medical','travel','employment','membership','general'].forEach(value => classification.append(node('option', { value, selected: vault.classification === value }, value)));
    const expiry = node('input', { type: 'date' }); expiry.value = vault.document_expiry_at || ''; const obligations = node('textarea', { rows: 7, maxlength: 200000 }); obligations.value = (vault.obligations || []).map(item => item.text).join('\n'); const sensitivity = node('select'); ['normal','confidential','sensitive','restricted'].forEach(value => sensitivity.append(node('option', { value, selected: source.sensitivity === value }, value))); const memory = node('input', { type: 'checkbox' }); memory.checked = source.allow_memory_suggestions;
    form.append(node('h3', {}, source.title), node('p', { class: 'om-empty' }, `${vault.analysis_method || 'manual review'} · ${vault.review_status || 'not reviewed'}`), field('Classification', classification), field('Document expiry', expiry), field('Obligations, one per line', obligations), field('Sensitivity', sensitivity), field('Allow memory suggestions from this source', memory), node('button', { type: 'submit', class: 'om-primary' }, 'Approve vault metadata'));
    form.addEventListener('submit', async (event) => { event.preventDefault(); try { const updated = await api(`/api/knowledge/sources/${encodeURIComponent(source.id)}/vault`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision: source.revision, classification: classification.value, document_expiry_at: expiry.value ? new Date(`${expiry.value}T00:00:00Z`).toISOString() : null, obligations: obligations.value.split('\n').map(value => value.trim()).filter(Boolean), sensitivity: sensitivity.value, allow_memory_suggestions: memory.checked }) }); announce(modal, 'Vault metadata approved with source provenance retained.'); await showVaultRecord(updated); await loadSources(); } catch (error) { announce(modal, error.message, true); } }); results.append(form); classification.focus();
  }
  async function showVault() {
    try { const data = await api('/api/knowledge/vault'); results.replaceChildren(node('h3', {}, 'Document vault')); if (!data.documents.length) results.append(node('p', { class: 'om-empty' }, 'No analyzed vault documents yet. Analyze a source to extract reviewable expiry and obligation evidence.')); data.documents.forEach(source => { const vault = source.vault; const card = node('article', { class: 'om-result-card' }); card.append(node('strong', {}, source.title), node('span', {}, `${vault.classification} · ${source.sensitivity}${vault.document_expiry_at ? ` · expires ${vault.document_expiry_at}` : ''}`), node('p', {}, `${vault.obligations?.length || 0} source-backed obligations · ${vault.review_status}`)); const open = node('button', { type: 'button' }, 'Review'); open.addEventListener('click', () => showVaultRecord(source)); card.append(open); results.append(card); }); } catch (error) { announce(modal, error.message, true); }
  }
  searchForm.addEventListener('submit', async (event) => {
    event.preventDefault(); if (!query.value.trim()) return;
    try {
      const data = await api(`/api/knowledge/search?query=${encodeURIComponent(query.value.trim())}&limit=12`); results.replaceChildren();
      if (data.insufficient_evidence) results.append(node('p', { class: 'om-empty' }, 'Insufficient evidence in your indexed sources. OM Automate will not invent an answer.'));
      data.results.forEach((item) => {
        const card = node('article', { class: 'om-result-card' });
        card.append(node('strong', {}, item.source_title), node('span', {}, item.section || `Excerpt ${item.position + 1}`), node('p', {}, item.excerpt));
        const link = node('a', { href: item.source_url, target: '_blank', rel: 'noopener' }, `Source ${item.source_id}`); card.append(link); results.append(card);
      });
    } catch (error) { announce(modal, error.message, true); }
  });
  upload.addEventListener('change', async () => {
    const file = upload.files[0]; if (!file) return;
    const data = new FormData(); data.append('file', file); data.append('sensitivity', 'normal'); data.append('allow_memory_suggestions', 'true');
    try { const source = await api('/api/knowledge/sources/upload', { method: 'POST', body: data }); if (['document','pdf','text','markdown','attachment','imported_record'].includes(source.type)) await api(`/api/knowledge/sources/${encodeURIComponent(source.id)}/analyze-vault`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true }) }); announce(modal, 'Source indexed with reviewable vault metadata.'); upload.value = ''; await loadSources(); } catch (error) { announce(modal, error.message, true); }
  });
  refresh.addEventListener('click', loadSources); vaultButton.addEventListener('click', showVault); newMemory.addEventListener('click', showNewMemory); refreshMemories.addEventListener('click', loadMemories); await Promise.all([loadSources(), loadMemories()]); query.focus();
}

function dashboardCard(title, items, formatter = (item) => String(item)) {
  const card = node('section', { class: 'om-dashboard-card' }); card.append(node('h3', {}, title));
  if (!items?.length) card.append(node('p', { class: 'om-empty' }, 'Nothing requiring attention.'));
  else {
    const list = node('ul'); items.slice(0, 12).forEach((item) => list.append(node('li', {}, formatter(item)))); card.append(list);
  }
  return card;
}

async function openToday() {
  const modal = openShell('Today', 'A source-grounded view of your day, decisions, commitments, and approvals.');
  const body = qs('.om-workspace-body', modal);
  const command = node('form', { class: 'om-knowledge-search' });
  const input = node('input', { placeholder: 'Ask OM or enter a quick command…', maxlength: 4000, 'aria-label': 'Quick command' });
  command.append(input, node('button', { type: 'submit', class: 'om-primary' }, 'Ask OM')); body.append(command);
  const clock = node('div', { class: 'om-today-clock' }); body.append(clock);
  const grid = node('div', { class: 'om-dashboard-grid' }); body.append(grid);
  command.addEventListener('submit', (event) => {
    event.preventDefault(); const chat = document.getElementById('message'); if (!chat || !input.value.trim()) return;
    chat.value = input.value.trim(); chat.dispatchEvent(new Event('input', { bubbles: true })); closeModal(modal); chat.focus();
  });
  try {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    const [data, metrics] = await Promise.all([api(`/api/dashboard/today?timezone=${encodeURIComponent(timezone)}`), api('/api/dashboard/metrics?days=30')]);
    clock.append(node('strong', {}, new Date(data.local_time).toLocaleString([], { dateStyle: 'full', timeStyle: 'short' })), node('span', {}, data.weather.message));
    const next = data.next_event ? [data.next_event] : [];
    grid.append(
      dashboardCard('Next event', next, (item) => item.summary || item.title || 'Untitled event'),
      dashboardCard('Priority tasks', data.priority_tasks, (item) => item.title),
      dashboardCard('Messages requiring attention', data.emails_requiring_attention, (item) => item.subject || item.snippet || 'Unread message'),
      dashboardCard('Pending approvals', data.pending_approvals, (item) => item.approval_reason || item.tool_name),
      dashboardCard('Unresolved commitments', data.unresolved_commitments, (item) => item.title),
      dashboardCard('Meeting actions', data.recent_meeting_actions, (item) => item.text),
      dashboardCard('Important reminders', data.important_reminders, (item) => item.message),
      dashboardCard('Full schedule', data.schedule, (item) => item.summary || item.title || 'Untitled event'),
      dashboardCard('Integration health', data.integration_health, (item) => `${item.email || item.connection_id} · Calendar ${item.calendar} · Gmail ${item.gmail}`),
      dashboardCard('Local Core health', data.local_core_health, (item) => `${item.name.replaceAll('_', ' ')} · ${item.status}`),
    );
    const metricGrid = node('div', { class: 'om-metric-grid', 'aria-label': 'Thirty day operating metrics' });
    [['Attention returned', `${metrics.attention_returned_items} items`], ['Recorded time returned', `${metrics.attention_returned_minutes} min`], ['Proposal acceptance', metrics.approvals.proposal_acceptance_rate == null ? 'No decisions yet' : `${Math.round(metrics.approvals.proposal_acceptance_rate * 100)}%`], ['Verified actions', String(metrics.approvals.verified)]].forEach(([label, value]) => { const metric = node('div', { class: 'om-metric' }); metric.append(node('span', {}, label), node('strong', {}, value)); metricGrid.append(metric); });
    body.append(metricGrid, node('p', { class: 'om-empty' }, metrics.measurement_note));
    const briefing = node('section', { class: 'om-briefing' }); const briefingHeader = node('div', { class: 'om-workspace-toolbar' });
    const briefingTitle = node('h3', {}, 'Morning briefing'); const briefingBody = node('div'); const history = node('div'); briefingHeader.append(briefingTitle);
    const renderBriefing = (record) => { briefingTitle.textContent = `${record.kind[0].toUpperCase()}${record.kind.slice(1)} briefing`; briefingBody.replaceChildren(); record.sections.forEach((section) => briefingBody.append(dashboardCard(`${section.title} · ${section.sources?.length || 0} sources`, section.sources?.length ? section.sources : section.items, (source) => typeof source === 'string' ? source : `${source.label} · ${source.type}${source.id ? ` · ${source.id}` : ''}`))); if (record.missing_sources?.length) briefingBody.append(node('p', { class: 'om-empty' }, `Unavailable sources: ${record.missing_sources.join(', ')}`)); };
    for (const kind of ['morning', 'evening', 'weekly']) {
      const button = node('button', { type: 'button' }, kind[0].toUpperCase() + kind.slice(1));
      button.addEventListener('click', async () => { try { renderBriefing(await api(`/api/dashboard/briefings/${kind}?timezone=${encodeURIComponent(timezone)}`)); } catch (error) { announce(modal, error.message, true); } }); briefingHeader.append(button);
    }
    const save = node('button', { type: 'button', class: 'om-primary' }, 'Save this briefing'); briefingHeader.append(save);
    save.addEventListener('click', async () => { const kind = briefingTitle.textContent.split(' ')[0].toLowerCase(); try { const saved = await api(`/api/dashboard/briefings/${kind}/runs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ timezone }) }); announce(modal, `${saved.kind} briefing saved with ${saved.source_count} sources.`); await loadHistory(); } catch (error) { announce(modal, error.message, true); } });
    async function loadHistory() { const saved = await api('/api/dashboard/briefings/runs?limit=8'); history.replaceChildren(node('h3', {}, 'Briefing history')); if (!saved.briefings.length) history.append(node('p', { class: 'om-empty' }, 'No saved briefing runs yet.')); saved.briefings.forEach((item) => { const button = node('button', { type: 'button', class: 'om-record-row' }); button.append(node('strong', {}, `${item.kind} · ${item.period_key}`), node('span', {}, `${item.source_count} sources`)); button.addEventListener('click', () => renderBriefing(item)); history.append(button); }); }
    briefing.append(briefingHeader, briefingBody, history); body.append(briefing); renderBriefing(data.daily_briefing); await loadHistory();
  } catch (error) { announce(modal, error.message, true); }
  input.focus();
}

async function openAutomations() {
  const modal = openShell('Automations', 'Validated triggers and bounded actions with run history, approvals, rate limits, and loop protection.');
  const body = qs('.om-workspace-body', modal); const toolbar = node('div', { class: 'om-workspace-toolbar' });
  const create = node('button', { type: 'button', class: 'om-primary' }, 'New automation'); const routines = node('button', { type: 'button' }, 'Routine templates'); const refresh = node('button', { type: 'button' }, 'Refresh'); const metrics = node('span', { class: 'om-empty' }); toolbar.append(create, routines, refresh, metrics);
  const columns = node('div', { class: 'om-workspace-columns' }); const list = node('div', { class: 'om-workspace-list' }); const detail = node('div', { class: 'om-workspace-detail' }); columns.append(list, detail); body.append(toolbar, columns);
  async function load() {
    try { const [data, measured] = await Promise.all([api('/api/automations'), api('/api/automations/metrics?days=30')]); metrics.textContent = `${measured.successful_routine_runs} routine runs · ${measured.attention_returned_minutes} min returned`; list.replaceChildren(); if (!data.automations.length) list.append(node('p', { class: 'om-empty' }, 'No structured automations yet.'));
      data.automations.forEach((item) => { const button = node('button', { type: 'button', class: 'om-record-row', onclick: () => show(item) }); button.append(node('strong', {}, item.name), node('span', {}, `${item.status} · ${item.trigger.type} · ${item.run_count} runs`)); list.append(button); });
    } catch (error) { announce(modal, error.message, true); }
  }
  async function showRoutines() {
    try { const data = await api('/api/automations/templates'); detail.replaceChildren(node('h3', {}, 'Recurring routines')); data.templates.forEach(template => { const card = node('article', { class: 'om-source-card' }); card.append(node('strong', {}, template.name), node('p', {}, template.description), node('small', {}, `${template.trigger_type.replaceAll('_',' ')} · ${template.estimated_minutes_saved} min estimated per successful run`)); const install = node('button', { type: 'button', disabled: Boolean(template.installed_automation_id) }, template.installed_automation_id ? 'Installed' : 'Install'); install.addEventListener('click', async () => { try { await api(`/api/automations/templates/${encodeURIComponent(template.key)}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true }) }); announce(modal, `${template.name} installed and scheduled durably.`); await load(); await showRoutines(); } catch (error) { announce(modal, error.message, true); } }); card.append(install); detail.append(card); }); } catch (error) { announce(modal, error.message, true); }
  }
  function showCreate() {
    detail.replaceChildren(); const form = node('form', { class: 'om-workspace-form' }); const name = node('input', { required: true, maxlength: 300 });
    const trigger = node('select'); ['manual', 'scheduled_time', 'new_email', 'calendar_before_event', 'task_due', 'meeting_completed', 'file_added', 'integration_event', 'webhook', 'recurring_interval', 'conditional_polling'].forEach((value) => trigger.append(node('option', { value }, value.replaceAll('_', ' '))));
    const action = node('select'); ['generate_briefing', 'create_task', 'draft_email', 'add_reminder', 'query_knowledge', 'run_research', 'notify_user', 'call_integration', 'request_approval', 'start_agent_workflow', 'create_backup'].forEach((value) => action.append(node('option', { value }, value.replaceAll('_', ' '))));
    const parameters = node('textarea', { rows: 6, placeholder: '{\n  "kind": "morning"\n}' }); parameters.value = '{}';
    const examples = { generate_briefing: { kind: 'morning' }, create_task: { title: 'Review follow-up' }, draft_email: { to: 'person@example.com', subject: 'Follow-up', body: 'Draft for review' }, add_reminder: { title: 'Reminder', message: 'Follow up', remind_at: new Date(Date.now() + 3600000).toISOString() }, query_knowledge: { query: 'meeting context' }, run_research: { topic: 'research topic' }, notify_user: { message: 'Automation completed' }, call_integration: { integration_id: 'rest-api', action: 'integration.call', parameters: {} }, request_approval: { reason: 'Continue this workflow' }, start_agent_workflow: { automation_id: 'target automation ID', inputs: {} }, create_backup: {} };
    parameters.value = JSON.stringify(examples[action.value], null, 2); action.addEventListener('change', () => { parameters.value = JSON.stringify(examples[action.value], null, 2); });
    form.append(node('h3', {}, 'New automation'), field('Name', name), field('Trigger', trigger), field('Action', action), field('Action parameters (JSON)', parameters), node('p', { class: 'om-empty' }, 'External communications and integration actions pause for approval. Maximum 25 steps, depth 3, and 20 runs/hour by default.'), node('button', { type: 'submit', class: 'om-primary' }, 'Create automation'));
    form.addEventListener('submit', async (event) => { event.preventDefault(); try { const triggerValue = { type: trigger.value }; if (trigger.value === 'recurring_interval') triggerValue.interval_seconds = 3600; if (trigger.value === 'conditional_polling') triggerValue.poll_seconds = 900; if (trigger.value === 'scheduled_time') triggerValue.at = new Date(Date.now() + 3600000).toISOString(); if (trigger.value === 'calendar_before_event') triggerValue.minutes_before = 60; await api('/api/automations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.value, trigger: triggerValue, conditions: [], actions: [{ type: action.value, parameters: JSON.parse(parameters.value || '{}') }], limits: { max_steps: 25, max_runs_per_hour: 20, disable_after_failures: 3 } }) }); announce(modal, 'Automation created with bounded safety controls.'); await load(); showCreate(); } catch (error) { announce(modal, error.message, true); } }); detail.append(form); name.focus();
  }
  async function show(item) {
    detail.replaceChildren(); detail.append(node('h3', {}, item.name), node('p', {}, item.description || `${item.trigger.type} workflow`)); const controls = node('div', { class: 'om-workspace-toolbar' });
    const toggle = node('button', { type: 'button' }, item.status === 'enabled' ? 'Pause' : 'Enable'); const run = node('button', { type: 'button', class: 'om-primary' }, 'Run now'); controls.append(toggle, run); detail.append(controls);
    toggle.addEventListener('click', async () => { try { await api(`/api/automations/${encodeURIComponent(item.id)}/status`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: item.status === 'enabled' ? 'paused' : 'enabled' }) }); await load(); } catch (error) { announce(modal, error.message, true); } });
    run.addEventListener('click', async () => { try { const result = await api(`/api/automations/${encodeURIComponent(item.id)}/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ inputs: {}, dedupe_key: `manual-${Date.now()}` }) }); announce(modal, `Run ${result.status}.`); await show(item); await load(); } catch (error) { announce(modal, error.message, true); } });
    try {
      const history = await api(`/api/automations/runs?automation_id=${encodeURIComponent(item.id)}&limit=50`); detail.append(node('h3', {}, 'Run history'));
      history.runs.forEach((record) => {
        const card = node('article', { class: 'om-source-card' });
        card.append(node('strong', {}, `${record.status} · ${new Date(record.started_at).toLocaleString()}`), node('span', {}, `${record.duration_ms || 0} ms · approval ${record.approval_state} · retry ${record.retry_status}`), node('small', {}, `Correlation ${record.correlation_id}`));
        if (record.error) card.append(node('p', {}, record.error));
        const recovery = node('div', { class: 'om-workspace-toolbar' });
        if (['running', 'approval_required'].includes(record.status)) {
          const cancel = node('button', { type: 'button' }, 'Cancel run'); recovery.append(cancel);
          cancel.addEventListener('click', async () => { if (!window.confirm('Cancel this run? A provider operation already in progress will be allowed to finish safely.')) return; try { await api(`/api/automations/runs/${encodeURIComponent(record.id)}/cancel`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true }) }); announce(modal, 'Cancellation recorded.'); await show(item); } catch (error) { announce(modal, error.message, true); } });
        }
        if (['failed', 'cancelled'].includes(record.status)) {
          const retry = node('button', { type: 'button', class: 'om-primary' }, 'Retry safely'); recovery.append(retry);
          retry.addEventListener('click', async () => { try { const result = await api(`/api/automations/runs/${encodeURIComponent(record.id)}/retry`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true }) }); announce(modal, `Retry ${result.status}.`); await show(item); } catch (error) { announce(modal, error.message, true); } });
        }
        if (recovery.childElementCount) card.append(recovery);
        detail.append(card);
      });
    } catch (error) { announce(modal, error.message, true); }
  }
  create.addEventListener('click', showCreate); routines.addEventListener('click', showRoutines); refresh.addEventListener('click', load); await load(); showCreate();
}

function bindButton(id, handler) {
  const button = document.getElementById(id); if (!button) return;
  button.addEventListener('click', handler);
  button.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); handler(); } });
}

bindButton('tool-meetings-btn', openMeetings);
bindButton('tool-knowledge-btn', openKnowledge);
bindButton('tool-today-btn', openToday);
bindButton('tool-work-btn', openWork);
bindButton('tool-life-btn', openLife);
bindButton('tool-integrations-health-btn', openIntegrationHealth);
bindButton('tool-automations-btn', openAutomations);
window.omWorkspaces = { openMeetings, openKnowledge, openToday, openWork, openLife, openIntegrationHealth, openAutomations };
