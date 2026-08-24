/**
 * OM Approval Centre — review and decide exact, durable agent actions.
 *
 * Server-originated values are inserted with textContent/value only.  The few
 * innerHTML assignments below are fixed application chrome or fixed SVGs.
 */

import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';
import { nextToolWindowZ } from './toolWindowZOrder.js';
import {
  buildMutationBody,
  extractApprovalDetail,
  extractApprovalItems,
  isExpired,
  normalizeApproval,
} from './approvalCore.js';

const MODAL_ID = 'approval-centre-modal';
const API_ROOT = '/api/approvals';
const POLL_MS = 30_000;

const state = {
  open: false,
  tab: 'pending',
  items: [],
  loading: false,
  requestSequence: 0,
  previousFocus: null,
  pollTimer: null,
};

let _dragReady = false;

function _el(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = String(text);
  return element;
}

function _button(label, action, className = '') {
  const button = _el('button', `approval-btn ${className}`.trim(), label);
  button.type = 'button';
  button.dataset.approvalAction = action;
  return button;
}

function _safeDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date : null;
}

function _formatDate(value) {
  const date = _safeDate(value);
  if (!date) return 'Not recorded';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

function _relativeExpiry(value, now = Date.now()) {
  const date = _safeDate(value);
  if (!date) return 'No expiry supplied';
  const delta = date.getTime() - now;
  if (delta <= 0) return 'Expired';
  const seconds = Math.ceil(delta / 1000);
  if (seconds < 60) return `Expires in ${seconds}s`;
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `Expires in ${minutes}m`;
  const hours = Math.ceil(minutes / 60);
  if (hours < 48) return `Expires in ${hours}h`;
  return `Expires in ${Math.ceil(hours / 24)}d`;
}

function _statusLabel(status) {
  return String(status || 'pending')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, letter => letter.toUpperCase());
}

function _selectorId(value) {
  const raw = String(value || '');
  if (globalThis.CSS && typeof globalThis.CSS.escape === 'function') return globalThis.CSS.escape(raw);
  return raw.replace(/[^a-zA-Z0-9_-]/g, character => `\\${character}`);
}

function _detailRow(label, value, className = '') {
  const row = _el('div', `approval-detail-row ${className}`.trim());
  row.append(_el('dt', 'approval-detail-label', label));
  row.append(_el('dd', 'approval-detail-value', value || 'Not supplied'));
  return row;
}

function _resultText(value) {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch (_) {
    return String(value);
  }
}

function _errorMessage(payload, fallback) {
  const detail = payload && (payload.detail || payload.error || payload.message);
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail === 'object') {
    try { return JSON.stringify(detail); } catch (_) {}
  }
  return fallback;
}

async function _request(path, options = {}) {
  const headers = { Accept: 'application/json', ...(options.headers || {}) };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers,
  });
  let payload = null;
  try { payload = await response.json(); } catch (_) {}
  if (!response.ok) {
    const error = new Error(_errorMessage(payload, `Approval request failed (${response.status}).`));
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function _setNotice(message = '', tone = 'info') {
  const notice = document.getElementById('approval-centre-notice');
  if (!notice) return;
  notice.textContent = message;
  notice.dataset.tone = tone;
  notice.hidden = !message;
}

function _setBusy(busy) {
  state.loading = !!busy;
  const refresh = document.getElementById('approval-centre-refresh');
  if (refresh) {
    refresh.disabled = state.loading;
    refresh.setAttribute('aria-busy', state.loading ? 'true' : 'false');
  }
}

function _badgeElements() {
  return [
    document.getElementById('approval-pending-badge'),
    document.getElementById('approval-rail-badge'),
  ].filter(Boolean);
}

function _setPendingCount(count) {
  const safe = Math.max(0, Number(count) || 0);
  for (const badge of _badgeElements()) {
    badge.textContent = safe > 99 ? '99+' : String(safe);
    badge.hidden = safe === 0;
    badge.setAttribute('aria-label', `${safe} pending approval${safe === 1 ? '' : 's'}`);
  }
  const titleCount = document.getElementById('approval-centre-pending-count');
  if (titleCount) titleCount.textContent = String(safe);
}

function _normaliseList(payload) {
  return extractApprovalItems(payload).map(normalizeApproval).filter(item => item.id);
}

async function refreshPendingBadge() {
  try {
    const payload = await _request(`${API_ROOT}?status=pending`);
    const items = _normaliseList(payload);
    const explicit = payload && Number(payload.pending_count);
    _setPendingCount(Number.isFinite(explicit) ? explicit : items.length);
    return items.length;
  } catch (_) {
    // The centre may be hidden for users without action permissions.  A badge
    // refresh is non-critical and must never interrupt the rest of the SPA.
    return null;
  }
}

function _renderLoading() {
  const list = document.getElementById('approval-centre-list');
  if (!list) return;
  list.replaceChildren();
  const shell = _el('div', 'approval-loading-state');
  shell.setAttribute('role', 'status');
  shell.append(_el('span', 'approval-loading-pulse'));
  shell.append(_el('span', '', 'Reading the action ledger…'));
  list.append(shell);
}

function _renderEmpty() {
  const list = document.getElementById('approval-centre-list');
  if (!list) return;
  const empty = _el('section', 'approval-empty-state');
  const mark = _el('div', 'approval-empty-mark');
  mark.setAttribute('aria-hidden', 'true');
  mark.textContent = state.tab === 'pending' ? '✓' : '—';
  empty.append(mark);
  empty.append(_el('h3', '', state.tab === 'pending' ? 'No decisions waiting' : 'No action history yet'));
  empty.append(_el(
    'p',
    '',
    state.tab === 'pending'
      ? 'OM has no pending actions. Consequential work will appear here before it can run.'
      : 'Approved, rejected, expired and completed actions will be recorded here.',
  ));
  list.append(empty);
}

function _renderArguments(item, card) {
  const section = _el('section', 'approval-arguments');
  section.setAttribute('aria-labelledby', `approval-arguments-title-${item.id}`);
  const header = _el('div', 'approval-section-heading');
  const title = _el('h4', '', 'Exact arguments');
  title.id = `approval-arguments-title-${item.id}`;
  header.append(title);
  if (item.status === 'pending') {
    const edit = _button('Edit JSON', 'edit-start', 'approval-btn-quiet');
    edit.setAttribute('aria-controls', `approval-editor-${item.id}`);
    header.append(edit);
  }
  section.append(header);

  const pre = _el('pre', 'approval-json');
  const code = _el('code', '', item.argumentsText);
  pre.append(code);
  section.append(pre);

  const editor = _el('div', 'approval-json-editor');
  editor.id = `approval-editor-${item.id}`;
  editor.hidden = true;
  const textarea = _el('textarea', 'approval-json-input');
  textarea.value = item.argumentsText;
  textarea.rows = 9;
  textarea.spellcheck = false;
  textarea.setAttribute('aria-label', `Edit exact JSON arguments for ${item.toolLabel}`);
  const error = _el('p', 'approval-field-error');
  error.setAttribute('role', 'alert');
  error.hidden = true;
  const controls = _el('div', 'approval-editor-controls');
  controls.append(_button('Cancel', 'edit-cancel', 'approval-btn-quiet'));
  controls.append(_button('Save arguments', 'edit-save', 'approval-btn-primary'));
  editor.append(textarea, error, controls);
  section.append(editor);
  card.append(section);
}

function _renderAffectedRecords(item, card) {
  if (!item.affectedRecords.length) return;
  const section = _el('section', 'approval-records');
  const heading = _el('h4', '', 'Affected records');
  section.append(heading);
  const list = _el('ul', 'approval-record-list');
  for (const record of item.affectedRecords) {
    const row = _el('li', 'approval-record');
    const label = _el('span', 'approval-record-label', record.label);
    row.append(label);
    const metadata = [record.type, record.id].filter(Boolean).join(' · ');
    if (metadata) row.append(_el('span', 'approval-record-meta', metadata));
    list.append(row);
  }
  section.append(list);
  card.append(section);
}

function _renderAudit(item, card) {
  if (!item.auditEvents.length) return;
  const section = _el('section', 'approval-audit');
  section.append(_el('h4', '', 'Action history'));
  const list = _el('ol', 'approval-audit-list');
  for (const raw of item.auditEvents) {
    const event = raw && typeof raw === 'object' ? raw : { event_type: String(raw) };
    const row = _el('li', 'approval-audit-event');
    const eventType = _statusLabel(event.event_type || event.type || 'Updated');
    row.append(_el('span', 'approval-audit-type', eventType));
    const at = event.occurred_at || event.created_at || event.timestamp;
    if (at) row.append(_el('time', 'approval-audit-time', _formatDate(at)));
    list.append(row);
  }
  section.append(list);
  card.append(section);
}

function _renderHistoryOutcome(item, card) {
  if (item.status === 'pending') return;
  const section = _el('section', 'approval-outcome');
  section.append(_el('h4', '', 'Outcome'));
  const grid = _el('dl', 'approval-outcome-grid');
  grid.append(_detailRow('Status', _statusLabel(item.status)));
  if (item.decidedAt) grid.append(_detailRow('Decision time', _formatDate(item.decidedAt)));
  if (item.decidedBy) grid.append(_detailRow('Decided by', item.decidedBy));
  if (item.decisionReason) grid.append(_detailRow('Decision note', item.decisionReason));
  if (item.verificationStatus) grid.append(_detailRow('Verification', _statusLabel(item.verificationStatus)));
  if (item.approvalRuleId) grid.append(_detailRow('Standing rule', item.approvalRuleId, 'is-mono'));
  section.append(grid);
  const result = _resultText(item.result);
  if (result) {
    const resultTitle = _el('h5', '', 'Recorded result');
    const resultPre = _el('pre', 'approval-result');
    resultPre.textContent = result;
    section.append(resultTitle, resultPre);
  }
  if (item.error) {
    const error = _el('p', 'approval-outcome-error', item.error);
    error.setAttribute('role', 'status');
    section.append(error);
  }
  card.append(section);

  if (item.status === 'executing') {
    const footer = _el('footer', 'approval-card-actions');
    footer.append(_button('Stop action', 'cancel-open', 'approval-btn-danger'));
    const panel = _el('div', 'approval-confirm-panel approval-reject-panel');
    panel.dataset.panel = 'cancel';
    panel.hidden = true;
    panel.setAttribute('role', 'region');
    panel.setAttribute('aria-label', 'Stop executing action');
    panel.append(_el(
      'p',
      '',
      'OM will interrupt local execution. An external effect that already started will be marked for reconciliation.',
    ));
    const label = _el('label', 'approval-reject-label', 'Reason (optional)');
    label.htmlFor = `approval-cancel-reason-${item.id}`;
    const reason = _el('textarea', 'approval-reject-input approval-cancel-input');
    reason.id = `approval-cancel-reason-${item.id}`;
    reason.rows = 2;
    reason.maxLength = 1000;
    const controls = _el('div', 'approval-inline-controls');
    controls.append(_button('Keep running', 'panel-cancel', 'approval-btn-quiet'));
    controls.append(_button('Confirm stop', 'cancel-confirm', 'approval-btn-danger'));
    panel.append(label, reason, controls);
    footer.append(panel);
    card.append(footer);
  }
}

function _renderDecisionControls(item, card) {
  if (item.status !== 'pending') return;
  const expired = isExpired(item);
  const footer = _el('footer', 'approval-card-actions');

  const primaryActions = _el('div', 'approval-primary-actions');
  const approve = _button('Approve once', 'approve-once', 'approval-btn-primary');
  approve.disabled = expired;
  primaryActions.append(approve);

  const always = _button('Always allow exact action', 'always-open', 'approval-btn-secondary');
  if (!item.alwaysAllowEligible) {
    always.disabled = true;
    always.setAttribute('aria-disabled', 'true');
    always.title = item.riskLevel >= 3
      ? 'Level 3 actions always require an explicit one-time confirmation.'
      : 'This action is not eligible for a standing approval rule.';
  }
  primaryActions.append(always);
  footer.append(primaryActions);

  const reject = _button('Reject', 'reject-open', 'approval-btn-danger');
  reject.disabled = expired;
  footer.append(reject);

  const scopePanel = _el('div', 'approval-confirm-panel');
  scopePanel.dataset.panel = 'always';
  scopePanel.hidden = true;
  scopePanel.setAttribute('role', 'region');
  scopePanel.setAttribute('aria-label', 'Confirm standing approval rule');
  scopePanel.append(_el(
    'p',
    '',
    `This creates a rule for ${item.toolLabel} v${item.toolVersion || 1} with this exact argument hash. `
      + 'It does not authorize different recipients, records or values.',
  ));
  const scopeControls = _el('div', 'approval-inline-controls');
  scopeControls.append(_button('Cancel', 'panel-cancel', 'approval-btn-quiet'));
  scopeControls.append(_button('Create rule & approve', 'always-confirm', 'approval-btn-primary'));
  scopePanel.append(scopeControls);
  footer.append(scopePanel);

  const rejectPanel = _el('div', 'approval-confirm-panel approval-reject-panel');
  rejectPanel.dataset.panel = 'reject';
  rejectPanel.hidden = true;
  rejectPanel.setAttribute('role', 'region');
  rejectPanel.setAttribute('aria-label', 'Reject action');
  const label = _el('label', 'approval-reject-label', 'Reason (optional)');
  label.htmlFor = `approval-reject-reason-${item.id}`;
  const reason = _el('textarea', 'approval-reject-input');
  reason.id = `approval-reject-reason-${item.id}`;
  reason.rows = 2;
  reason.maxLength = 1000;
  reason.placeholder = 'Tell OM why this action should not run';
  const rejectControls = _el('div', 'approval-inline-controls');
  rejectControls.append(_button('Cancel', 'panel-cancel', 'approval-btn-quiet'));
  rejectControls.append(_button('Confirm rejection', 'reject-confirm', 'approval-btn-danger'));
  rejectPanel.append(label, reason, rejectControls);
  footer.append(rejectPanel);

  if (expired) {
    const expiredNote = _el('p', 'approval-expired-note', 'This approval has expired. Refresh to load its final status.');
    footer.append(expiredNote);
  } else if (item.riskLevel >= 3) {
    footer.append(_el(
      'p',
      'approval-level-three-note',
      'Level 3 · one-time approval only. A standing rule can never be created for this action.',
    ));
  }
  card.append(footer);
}

function _renderCard(item, index) {
  const card = _el('article', `approval-card risk-${item.riskLevel}`);
  card.dataset.approvalId = item.id;
  card.dataset.status = item.status;
  card.style.setProperty('--approval-order', String(index));
  card.style.setProperty('--approval-delay', `${Math.min(index, 8) * 34}ms`);
  card.setAttribute('aria-labelledby', `approval-title-${item.id}`);

  const top = _el('header', 'approval-card-header');
  const risk = _el('span', `approval-risk-badge risk-${item.riskLevel}`, `Level ${item.riskLevel} · ${item.riskLabel}`);
  top.append(risk);
  const status = _el('span', `approval-status-badge status-${item.status}`, _statusLabel(item.status));
  top.append(status);
  const refresh = _button('Refresh action details', 'refresh-one', 'approval-icon-btn');
  refresh.textContent = '↻';
  refresh.title = 'Refresh this action record';
  refresh.setAttribute('aria-label', `Refresh ${item.toolLabel} approval details`);
  top.append(refresh);
  card.append(top);

  const identity = _el('div', 'approval-identity');
  const eyebrow = _el('div', 'approval-tool-name');
  eyebrow.append(_el('span', '', item.toolLabel));
  if (item.toolVersion) eyebrow.append(_el('span', 'approval-tool-version', `v${item.toolVersion}`));
  identity.append(eyebrow);
  const title = _el('h3', '', item.action || item.toolLabel);
  title.id = `approval-title-${item.id}`;
  identity.append(title);
  card.append(identity);

  const context = _el('dl', 'approval-context-grid');
  context.append(_detailRow('Why approval is required', item.reason || `Risk Level ${item.riskLevel} policy`));
  const expiryRow = _detailRow('Expiry', _relativeExpiry(item.expiresAt), 'approval-expiry-row');
  const expiryValue = expiryRow.querySelector('.approval-detail-value');
  if (expiryValue && item.expiresAt) {
    expiryValue.dataset.expiresAt = String(item.expiresAt);
    expiryValue.title = _formatDate(item.expiresAt);
  }
  context.append(expiryRow);
  if (item.createdAt) context.append(_detailRow('Requested', _formatDate(item.createdAt)));
  if (item.origin) context.append(_detailRow('Origin', _statusLabel(item.origin)));
  card.append(context);

  if (item.sessionId) {
    const conversation = _el('div', 'approval-conversation');
    conversation.append(_el('span', 'approval-conversation-label', 'Requested from'));
    const open = _button(item.conversationTitle, 'view-conversation', 'approval-conversation-link');
    open.dataset.sessionId = item.sessionId;
    open.title = `Open conversation ${item.conversationTitle}`;
    conversation.append(open);
    card.append(conversation);
  }

  _renderArguments(item, card);
  _renderAffectedRecords(item, card);
  _renderHistoryOutcome(item, card);
  _renderAudit(item, card);
  _renderDecisionControls(item, card);
  return card;
}

function _updateExpiryClocks() {
  document.querySelectorAll(`#${MODAL_ID} [data-expires-at]`).forEach(element => {
    element.textContent = _relativeExpiry(element.dataset.expiresAt);
    element.classList.toggle('is-expired', element.textContent === 'Expired');
  });
}

function _renderList() {
  const list = document.getElementById('approval-centre-list');
  if (!list) return;
  list.replaceChildren();
  if (!state.items.length) {
    _renderEmpty();
  } else {
    state.items.forEach((item, index) => list.append(_renderCard(item, index)));
  }
  const visibleCount = document.getElementById('approval-centre-visible-count');
  if (visibleCount) visibleCount.textContent = String(state.items.length);
  _updateExpiryClocks();
}

function _setTab(tab) {
  state.tab = tab === 'history' ? 'history' : 'pending';
  document.querySelectorAll('[data-approval-tab]').forEach(button => {
    const active = button.dataset.approvalTab === state.tab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
    button.tabIndex = active ? 0 : -1;
  });
  const heading = document.getElementById('approval-centre-list-title');
  if (heading) heading.textContent = state.tab === 'pending' ? 'Pending decisions' : 'Completed action history';
}

async function loadApprovals({ announce = false } = {}) {
  const sequence = ++state.requestSequence;
  _setBusy(true);
  _renderLoading();
  try {
    const payload = await _request(`${API_ROOT}?status=${encodeURIComponent(state.tab)}`);
    if (sequence !== state.requestSequence) return;
    state.items = _normaliseList(payload);
    _renderList();
    if (state.tab === 'pending') {
      const explicit = payload && Number(payload.pending_count);
      _setPendingCount(Number.isFinite(explicit) ? explicit : state.items.length);
    }
    if (announce) _setNotice('Approval ledger refreshed.', 'success');
  } catch (error) {
    if (sequence !== state.requestSequence) return;
    state.items = [];
    _renderList();
    _setNotice(error.message || 'Could not load approvals.', 'error');
  } finally {
    if (sequence === state.requestSequence) _setBusy(false);
  }
}

function _replaceItem(item) {
  const index = state.items.findIndex(current => current.id === item.id);
  if (index >= 0) state.items.splice(index, 1, item);
  else state.items.unshift(item);
  _renderList();
}

async function _readDetail(id) {
  const payload = await _request(`${API_ROOT}/${encodeURIComponent(id)}`);
  const rawDetail = extractApprovalDetail(payload);
  const detail = rawDetail && payload && Array.isArray(payload.events)
    ? { ...rawDetail, audit_events: payload.events, audit_chain_valid: payload.chain_valid }
    : rawDetail;
  const item = detail ? normalizeApproval(detail) : null;
  if (!item || !item.id) throw new Error('The approval detail response was incomplete.');
  return item;
}

async function _fetchDetail(id) {
  const item = await _readDetail(id);
  _replaceItem(item);
  return item;
}

async function _guardFresh(original) {
  // Do not re-render an unchanged card here: the original remains aria-busy
  // and disabled until the mutation completes, preventing a rapid second
  // click from racing the first approval request.
  const latest = await _readDetail(original.id);
  if (latest.revision !== original.revision || latest.argumentsHash !== original.argumentsHash) {
    _replaceItem(latest);
    _setNotice('This action changed while you were reviewing it. Read the refreshed arguments before deciding.', 'warning');
    const card = document.querySelector(`[data-approval-id="${_selectorId(original.id)}"]`);
    card?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    return null;
  }
  return latest;
}

function _cardItem(target) {
  const card = target.closest('[data-approval-id]');
  if (!card) return { card: null, item: null };
  return {
    card,
    item: state.items.find(candidate => candidate.id === card.dataset.approvalId) || null,
  };
}

function _setCardMutating(card, active) {
  if (!card) return;
  card.classList.toggle('is-mutating', !!active);
  card.setAttribute('aria-busy', active ? 'true' : 'false');
  card.querySelectorAll('button, textarea').forEach(control => {
    if (active) {
      control.dataset.approvalWasDisabled = control.disabled ? '1' : '0';
      control.disabled = true;
    } else if (control.dataset.approvalWasDisabled !== undefined) {
      control.disabled = control.dataset.approvalWasDisabled === '1';
      delete control.dataset.approvalWasDisabled;
    }
  });
}

async function _handleConflict(error) {
  if (error && error.status === 409) {
    _setNotice('The action was updated or decided elsewhere. The ledger has been refreshed.', 'warning');
    await loadApprovals();
    return true;
  }
  return false;
}

async function _mutate(card, item, kind, extras = {}) {
  _setCardMutating(card, true);
  try {
    const fresh = await _guardFresh(item);
    if (!fresh) return;
    let path = `${API_ROOT}/${encodeURIComponent(item.id)}`;
    let method = 'PATCH';
    if (kind === 'approve') {
      path += '/approve';
      method = 'POST';
    } else if (kind === 'reject') {
      path += '/reject';
      method = 'POST';
    } else if (kind === 'cancel') {
      path += '/cancel';
      method = 'POST';
    }
    const body = buildMutationBody(fresh, kind, extras);
    await _request(path, { method, body: JSON.stringify(body) });
    const verb = kind === 'edit'
      ? 'Arguments updated.'
      : kind === 'reject'
        ? 'Action rejected.'
        : kind === 'cancel'
          ? 'Cancellation requested. Check reconciliation status before retrying.'
          : 'Action approved.';
    _setNotice(verb, 'success');
    await loadApprovals();
    await refreshPendingBadge();
  } catch (error) {
    if (!(await _handleConflict(error))) {
      _setNotice(error.message || 'The approval could not be updated.', 'error');
    }
  } finally {
    _setCardMutating(card, false);
  }
}

function _openPanel(card, name) {
  card.querySelectorAll('[data-panel]').forEach(panel => { panel.hidden = panel.dataset.panel !== name; });
  const panel = card.querySelector(`[data-panel="${name}"]`);
  panel?.querySelector('textarea, button:not([disabled])')?.focus();
}

function _closePanels(card) {
  card.querySelectorAll('[data-panel]').forEach(panel => { panel.hidden = true; });
}

async function _startEdit(card, item) {
  _setCardMutating(card, true);
  try {
    const latest = await _fetchDetail(item.id);
    const updatedCard = document.querySelector(`[data-approval-id="${_selectorId(latest.id)}"]`);
    const editor = updatedCard?.querySelector('.approval-json-editor');
    const pre = updatedCard?.querySelector('.approval-json');
    const editButton = updatedCard?.querySelector('[data-approval-action="edit-start"]');
    if (editor) editor.hidden = false;
    if (pre) pre.hidden = true;
    if (editButton) editButton.hidden = true;
    editor?.querySelector('textarea')?.focus();
  } catch (error) {
    _setNotice(error.message || 'Could not refresh the action before editing.', 'error');
    _setCardMutating(card, false);
  }
}

function _cancelEdit(card) {
  const editor = card.querySelector('.approval-json-editor');
  const pre = card.querySelector('.approval-json');
  const editButton = card.querySelector('[data-approval-action="edit-start"]');
  if (editor) editor.hidden = true;
  if (pre) pre.hidden = false;
  if (editButton) {
    editButton.hidden = false;
    editButton.focus();
  }
}

async function _saveEdit(card, item) {
  const textarea = card.querySelector('.approval-json-input');
  const error = card.querySelector('.approval-field-error');
  let argumentsObject;
  try {
    argumentsObject = JSON.parse(textarea?.value || '');
    if (!argumentsObject || typeof argumentsObject !== 'object' || Array.isArray(argumentsObject)) {
      throw new Error('The top-level JSON value must be an object.');
    }
  } catch (parseError) {
    if (error) {
      error.textContent = parseError.message || 'Enter valid JSON.';
      error.hidden = false;
    }
    textarea?.setAttribute('aria-invalid', 'true');
    textarea?.focus();
    return;
  }
  if (error) error.hidden = true;
  textarea?.removeAttribute('aria-invalid');
  await _mutate(card, item, 'edit', { arguments: argumentsObject });
}

async function _openConversation(sessionId) {
  if (!sessionId || !window.sessionModule?.selectSession) return;
  closeApprovalCentre();
  if (window.sessionModule.loadSessions) await window.sessionModule.loadSessions().catch(() => {});
  await window.sessionModule.selectSession(sessionId);
}

async function _onListClick(event) {
  const control = event.target.closest('[data-approval-action]');
  if (!control) return;
  const action = control.dataset.approvalAction;
  const { card, item } = _cardItem(control);
  if (!card || !item) return;
  event.preventDefault();

  if (action === 'refresh-one') {
    _setCardMutating(card, true);
    try {
      await _fetchDetail(item.id);
      _setNotice('Exact action record refreshed.', 'success');
    } catch (error) {
      _setNotice(error.message || 'Could not refresh this action.', 'error');
      _setCardMutating(card, false);
    }
  } else if (action === 'edit-start') {
    await _startEdit(card, item);
  } else if (action === 'edit-cancel') {
    _cancelEdit(card);
  } else if (action === 'edit-save') {
    await _saveEdit(card, item);
  } else if (action === 'approve-once') {
    await _mutate(card, item, 'approve', { alwaysAllow: false });
  } else if (action === 'always-open') {
    _openPanel(card, 'always');
  } else if (action === 'always-confirm') {
    await _mutate(card, item, 'approve', { alwaysAllow: true });
  } else if (action === 'reject-open') {
    _openPanel(card, 'reject');
  } else if (action === 'reject-confirm') {
    const reason = card.querySelector('.approval-reject-input')?.value || '';
    await _mutate(card, item, 'reject', { reason });
  } else if (action === 'cancel-open') {
    _openPanel(card, 'cancel');
  } else if (action === 'cancel-confirm') {
    const reason = card.querySelector('.approval-cancel-input')?.value || '';
    await _mutate(card, item, 'cancel', { reason });
  } else if (action === 'panel-cancel') {
    _closePanels(card);
  } else if (action === 'view-conversation') {
    await _openConversation(control.dataset.sessionId || item.sessionId);
  }
}

function _ensureModal() {
  let modal = document.getElementById(MODAL_ID);
  if (modal) return modal;
  modal = _el('div', 'modal hidden approval-centre-modal');
  modal.id = MODAL_ID;
  modal.innerHTML = `
    <div class="modal-content approval-centre-content" role="dialog" aria-modal="false" aria-labelledby="approval-centre-title">
      <div class="modal-header approval-centre-header">
        <div class="approval-brand-mark" aria-hidden="true"><span>OM</span></div>
        <div class="approval-title-block">
          <span class="approval-kicker">CONTROL LEDGER</span>
          <h4 id="approval-centre-title">Approval Centre</h4>
        </div>
        <div class="approval-header-stat" title="Pending actions">
          <span id="approval-centre-pending-count">0</span>
          <small>pending</small>
        </div>
        <button type="button" class="close-btn" id="approval-centre-close" aria-label="Close Approval Centre">✖</button>
      </div>
      <div class="approval-centre-body">
        <div class="approval-toolbar">
          <div class="approval-tabs" role="tablist" aria-label="Approval views">
            <button type="button" class="approval-tab active" data-approval-tab="pending" role="tab" aria-selected="true">Pending</button>
            <button type="button" class="approval-tab" data-approval-tab="history" role="tab" aria-selected="false" tabindex="-1">History</button>
          </div>
          <p class="approval-toolbar-copy">Review the exact action OM intends to take before anything consequential runs.</p>
          <button type="button" class="approval-refresh" id="approval-centre-refresh" aria-label="Refresh approval ledger" title="Refresh approval ledger">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            Refresh
          </button>
        </div>
        <div id="approval-centre-notice" class="approval-notice" role="status" aria-live="polite" hidden></div>
        <div class="approval-list-heading">
          <h2 id="approval-centre-list-title">Pending decisions</h2>
          <span><strong id="approval-centre-visible-count">0</strong> records</span>
        </div>
        <div id="approval-centre-list" class="approval-list" aria-live="polite" aria-busy="false"></div>
      </div>
    </div>`;
  document.body.append(modal);

  const list = modal.querySelector('#approval-centre-list');
  list.addEventListener('click', event => { _onListClick(event).catch(console.error); });
  modal.querySelector('#approval-centre-refresh').addEventListener('click', () => loadApprovals({ announce: true }));
  modal.querySelectorAll('[data-approval-tab]').forEach(button => {
    button.addEventListener('click', () => {
      if (state.tab === button.dataset.approvalTab) return;
      _setTab(button.dataset.approvalTab);
      _setNotice();
      loadApprovals();
    });
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const next = button.dataset.approvalTab === 'pending' ? 'history' : 'pending';
      const target = modal.querySelector(`[data-approval-tab="${next}"]`);
      target?.click();
      target?.focus();
    });
  });
  modal.querySelector('#approval-centre-close').addEventListener('click', closeApprovalCentre);
  modal.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const visiblePanel = modal.querySelector('[data-panel]:not([hidden])');
    const visibleEditor = modal.querySelector('.approval-json-editor:not([hidden])');
    if (visiblePanel) {
      event.preventDefault();
      visiblePanel.hidden = true;
    } else if (visibleEditor) {
      event.preventDefault();
      _cancelEdit(visibleEditor.closest('[data-approval-id]'));
    } else {
      closeApprovalCentre();
    }
  });

  if (!_dragReady) {
    makeWindowDraggable(modal, {
      content: modal.querySelector('.modal-content'),
      header: modal.querySelector('.modal-header'),
      skipSelector: 'button, input, textarea, a, [role="tab"]',
    });
    _dragReady = true;
  }
  return modal;
}

function _hideModal() {
  const modal = document.getElementById(MODAL_ID);
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('modal-minimized');
  modal.style.display = '';
  state.open = false;
  if (state.previousFocus && document.contains(state.previousFocus)) state.previousFocus.focus();
  state.previousFocus = null;
}

export function openApprovalCentre() {
  const modal = _ensureModal();
  if (Modals.isMinimized(MODAL_ID)) {
    Modals.restore(MODAL_ID);
    state.open = true;
    loadApprovals();
    return;
  }
  if (state.open && !modal.classList.contains('hidden')) {
    modal.style.zIndex = String(nextToolWindowZ({ exclude: modal, floor: 280 }));
    return;
  }
  state.previousFocus = document.activeElement;
  state.open = true;
  modal.classList.remove('hidden', 'modal-minimized');
  modal.style.display = 'flex';
  modal.style.zIndex = String(nextToolWindowZ({ exclude: modal, floor: 280 }));
  Modals.register(MODAL_ID, {
    railBtnId: 'rail-approvals',
    sidebarBtnId: 'tool-approvals-btn',
    label: 'Approvals',
    closeFn: _hideModal,
    restoreFn: () => loadApprovals(),
  });
  Modals.injectMinimizeButton(modal, MODAL_ID);
  _setTab(state.tab);
  _setNotice();
  loadApprovals();
  requestAnimationFrame(() => modal.querySelector('[role="tab"][aria-selected="true"]')?.focus());
}

export function closeApprovalCentre() {
  if (Modals.isRegistered(MODAL_ID)) Modals.close(MODAL_ID);
  else _hideModal();
}

export function toggleApprovalCentre() {
  if (Modals.isMinimized(MODAL_ID)) {
    Modals.restore(MODAL_ID);
    state.open = true;
    loadApprovals();
    return;
  }
  const modal = document.getElementById(MODAL_ID);
  if (state.open && modal && !modal.classList.contains('hidden')) closeApprovalCentre();
  else openApprovalCentre();
}

export function isApprovalCentreOpen() {
  const modal = document.getElementById(MODAL_ID);
  return !!(state.open && modal && !modal.classList.contains('hidden'));
}

export function initApprovalCentre() {
  if (state.pollTimer) return;
  refreshPendingBadge();
  state.pollTimer = window.setInterval(() => {
    if (document.visibilityState !== 'hidden') refreshPendingBadge();
  }, POLL_MS);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'hidden') refreshPendingBadge();
  });
}

export default {
  init: initApprovalCentre,
  open: openApprovalCentre,
  close: closeApprovalCentre,
  toggle: toggleApprovalCentre,
  isOpen: isApprovalCentreOpen,
  refreshPendingBadge,
};
