// Read-only viewer for an approved plan that is already being executed. Plan
// proposal/approval UI intentionally lives elsewhere; this module only keeps a
// previously opened draggable/dockable view current as progress events arrive.

import uiModule from './ui.js';
import markdownModule from './markdown.js';
import { makeWindowDraggable } from './windowDrag.js';

let _modal = null;
let _shownPlanId = '';

function _record(value) {
  if (typeof value === 'string') return { text: value, plan_id: '', version: 0 };
  return value && typeof value === 'object' ? value : { text: '', plan_id: '', version: 0 };
}

function _getModal() {
  if (_modal) return _modal;
  _modal = document.createElement('div');
  _modal.id = 'plan-window';
  _modal.className = 'modal';
  _modal.style.display = 'none';
  _modal.innerHTML = `
    <div class="modal-content plan-window-content">
      <div class="modal-header">
        <h4><span id="plan-window-title">Approved plan</span></h4>
        <button class="close-btn" id="plan-window-close" aria-label="Close approved plan">✖</button>
      </div>
      <div class="modal-body plan-window-body" id="plan-window-body"></div>
    </div>`;
  document.body.appendChild(_modal);
  _modal.querySelector('#plan-window-close').addEventListener('click', closePlanWindow);
  const content = _modal.querySelector('.modal-content');
  const header = _modal.querySelector('.modal-header');
  if (content && header) makeWindowDraggable(_modal, { content, header });
  return _modal;
}

function _render(value) {
  const record = _record(value);
  const modal = _getModal();
  const body = modal.querySelector('#plan-window-body');
  _shownPlanId = String(record.plan_id || '');
  if (body) {
    body.dataset.planId = _shownPlanId;
    body.dataset.version = String(record.version ?? 0);
    body.innerHTML = markdownModule.processWithThinking(
      markdownModule.squashOutsideCode(String(record.text || ''))
    );
    if (window.hljs) {
      body.querySelectorAll('pre code').forEach((block) => window.hljs.highlightElement(block));
    }
  }
  return modal;
}

export function openPlanWindow(value) {
  const modal = _render(value);
  modal.style.display = 'flex';
  if (uiModule && uiModule.scrollHistory) {
    try { uiModule.scrollHistory(); } catch (_) {}
  }
}

export function closePlanWindow() {
  if (_modal) _modal.style.display = 'none';
}

export function isPlanWindowOpen() {
  return !!(_modal && _modal.style.display !== 'none');
}

export function updateOpenPlanWindow(value) {
  if (!isPlanWindowOpen()) return false;
  const record = _record(value);
  if (_shownPlanId && record.plan_id && String(record.plan_id) !== _shownPlanId) return false;
  _render(record);
  return true;
}

export default {
  openPlanWindow,
  closePlanWindow,
  isPlanWindowOpen,
  updateOpenPlanWindow,
};
