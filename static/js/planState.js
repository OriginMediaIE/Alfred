// Versioned browser state for the one approved plan associated with the
// current chat. Server updates are compare-and-set: an event is accepted only
// when it advances the exact session, plan id, and version the browser sent.

import Storage from './storage.js';

const SCHEMA_VERSION = 1;
const MAX_PLAN_CHARS = 8192;

function _integerVersion(value, fallback = null) {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : fallback;
}

function _legacyPlanId(sessionId) {
  // Stable, dependency-free FNV-1a hash. This gives records written by the old
  // {sid, text} store a durable identity without treating their text as an id.
  let hash = 0x811c9dc5;
  for (const char of String(sessionId || '')) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 0x01000193);
  }
  return `legacy-${(hash >>> 0).toString(16).padStart(8, '0')}`;
}

function _normaliseRecord(value) {
  if (!value || typeof value !== 'object') return null;
  const sid = String(value.sid ?? value.session_id ?? value.sessionId ?? '').trim();
  const text = String(value.text ?? value.plan ?? '').trim().slice(0, MAX_PLAN_CHARS);
  if (!sid || !text || value.active === false) return null;

  const suppliedId = value.plan_id ?? value.planId;
  const planId = String(suppliedId || _legacyPlanId(sid)).trim().slice(0, 128);
  if (!planId) return null;

  return {
    schema_version: SCHEMA_VERSION,
    sid,
    plan_id: planId,
    version: _integerVersion(value.version, 0),
    text,
    active: true,
  };
}

export function activatePlan({ sessionId, planId, text, version = 0 } = {}) {
  const record = _normaliseRecord({
    sid: sessionId,
    plan_id: planId,
    text,
    version,
    active: true,
  });
  if (!record) return null;
  Storage.setJSON(Storage.KEYS.PLAN, record);
  return record;
}

export function getActivePlan(sessionId) {
  const raw = Storage.getJSON(Storage.KEYS.PLAN, null);
  const record = _normaliseRecord(raw);
  if (!record || record.sid !== String(sessionId || '')) return null;

  // Transparently migrate the legacy {sid, text} record and normalise records
  // written by earlier builds before returning them to the request path.
  if (
    raw.schema_version !== SCHEMA_VERSION
    || raw.plan_id !== record.plan_id
    || raw.version !== record.version
    || raw.active !== true
  ) {
    Storage.setJSON(Storage.KEYS.PLAN, record);
  }
  return record;
}

export function clearActivePlan(sessionId) {
  const current = getActivePlan(sessionId);
  if (!current) return false;
  Storage.remove(Storage.KEYS.PLAN);
  return true;
}

export function applyPlanUpdate(update, currentSessionId, options = {}) {
  const current = getActivePlan(currentSessionId);
  if (!current) return { applied: false, reason: 'no-active-plan' };
  if (!update || typeof update !== 'object') {
    return { applied: false, reason: 'invalid-update' };
  }

  const sessionId = String(update.session_id ?? update.sessionId ?? '');
  const planId = String(update.plan_id ?? update.planId ?? '');
  const baseVersion = _integerVersion(update.base_version ?? update.baseVersion);
  const version = _integerVersion(update.version);
  const text = String(update.plan ?? update.text ?? '').trim().slice(0, MAX_PLAN_CHARS);

  if (sessionId !== current.sid || sessionId !== String(currentSessionId || '')) {
    return { applied: false, reason: 'session-mismatch' };
  }
  if (planId !== current.plan_id) {
    return { applied: false, reason: 'plan-mismatch' };
  }
  if (baseVersion !== current.version || version !== baseVersion + 1) {
    return { applied: false, reason: 'stale-version' };
  }
  if (!text) return { applied: false, reason: 'empty-plan' };

  const next = {
    ...current,
    text,
    version,
  };
  Storage.setJSON(Storage.KEYS.PLAN, next);

  if (typeof options.onApplied === 'function') {
    try { options.onApplied(next); } catch (error) {
      console.warn('[Plan] Failed to refresh open plan window:', error);
    }
  }
  try {
    if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
      window.dispatchEvent(new CustomEvent('odysseus:plan-updated', { detail: next }));
    }
  } catch (_) { /* Event support is best-effort outside the browser. */ }

  return { applied: true, record: next };
}

export default {
  activatePlan,
  getActivePlan,
  clearActivePlan,
  applyPlanUpdate,
};
