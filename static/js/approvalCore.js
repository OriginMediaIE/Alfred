/**
 * Pure Approval Centre data helpers.
 *
 * Kept DOM-free so the stale-write guards and risk rules can be exercised in
 * Node as well as in the browser.  The API is intentionally tolerant of the
 * list/detail wrappers used during migrations. Every mutation carries the
 * reviewed revision; approval additionally binds the exact argument hash.
 */

const LIST_KEYS = ['approvals', 'actions', 'items', 'results'];

function _isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function _first(record, keys, fallback = null) {
  for (const key of keys) {
    if (record && record[key] !== undefined && record[key] !== null) return record[key];
  }
  return fallback;
}

function _jsonValue(value, fallback) {
  if (typeof value !== 'string') return value === undefined || value === null ? fallback : value;
  try {
    return JSON.parse(value);
  } catch (_) {
    return fallback;
  }
}

function _objectValue(value) {
  const parsed = _jsonValue(value, null);
  return _isObject(parsed) ? parsed : {};
}

function _arrayValue(value) {
  const parsed = _jsonValue(value, null);
  if (Array.isArray(parsed)) return parsed;
  if (parsed === undefined || parsed === null || parsed === '') return [];
  return [parsed];
}

export function extractApprovalItems(payload) {
  if (Array.isArray(payload)) return payload;
  if (!_isObject(payload)) return [];
  for (const key of LIST_KEYS) {
    if (Array.isArray(payload[key])) return payload[key];
  }
  return [];
}

export function extractApprovalDetail(payload) {
  if (!_isObject(payload)) return null;
  for (const key of ['approval', 'action', 'item']) {
    if (_isObject(payload[key])) return payload[key];
  }
  return payload;
}

export function parseRiskLevel(value) {
  if (_isObject(value)) value = _first(value, ['level', 'value', 'number'], 0);
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.max(0, Math.min(3, Math.trunc(value)));
  }
  const match = String(value ?? '').match(/[0-3]/);
  return match ? Number(match[0]) : 0;
}

export function riskLabel(level) {
  const n = parseRiskLevel(level);
  return ['Read-only', 'Low risk', 'Consequential', 'Sensitive'][n];
}

export function humanizeToolName(value) {
  const raw = String(value || 'Unknown action').trim();
  if (!raw) return 'Unknown action';
  return raw
    .replace(/^mcp__[^_]+__/, '')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, char => char.toUpperCase());
}

function _normaliseRecord(record) {
  if (typeof record === 'string' || typeof record === 'number') {
    return { label: String(record), id: '', type: '', url: '' };
  }
  if (!_isObject(record)) return { label: 'Affected record', id: '', type: '', url: '' };
  const id = String(_first(record, ['id', 'record_id', 'resource_id'], '') || '');
  const type = String(_first(record, ['type', 'record_type', 'resource_type'], '') || '');
  const label = String(
    _first(record, ['label', 'title', 'name', 'summary'], '')
      || [type, id].filter(Boolean).join(' · ')
      || 'Affected record',
  );
  return {
    label,
    id,
    type,
    url: String(_first(record, ['url', 'href'], '') || ''),
  };
}

export function normalizeApproval(input) {
  const record = _isObject(input) ? input : {};
  const preview = _isObject(record.action_preview) ? record.action_preview : {};
  const conversation = _isObject(record.conversation) ? record.conversation : {};
  const riskSource = _first(record, ['risk_level', 'risk'], _first(preview, ['risk_level', 'risk'], 0));
  const riskLevel = parseRiskLevel(riskSource);
  const rawArguments = _first(
    record,
    ['arguments', 'arguments_json', 'action_arguments'],
    _first(preview, ['arguments', 'arguments_json'], {}),
  );
  const argumentsObject = _objectValue(rawArguments);
  const revisionValue = Number(_first(record, ['revision', 'version_revision'], 0));
  const status = String(_first(record, ['status', 'state'], 'pending') || 'pending').toLowerCase();
  const tool = String(
    _first(record, ['tool_name', 'tool', 'requested_tool'], _first(preview, ['tool', 'tool_name'], '')) || '',
  );
  const records = _arrayValue(
    _first(record, ['affected_records', 'records', 'resources', 'targets'], []),
  ).map(_normaliseRecord);
  const sessionId = String(
    _first(record, ['session_id', 'conversation_id'], _first(conversation, ['id', 'session_id'], '')) || '',
  );

  return {
    id: String(_first(record, ['id', 'action_id', 'approval_id'], '') || ''),
    revision: Number.isInteger(revisionValue) && revisionValue >= 0 ? revisionValue : 0,
    argumentsHash: String(
      _first(record, ['arguments_hash', 'argument_hash'], _first(preview, ['arguments_hash'], '')) || '',
    ),
    arguments: argumentsObject,
    argumentsText: JSON.stringify(argumentsObject, null, 2),
    tool,
    toolLabel: humanizeToolName(tool),
    toolVersion: Number(_first(record, ['tool_version'], _first(preview, ['tool_version'], 0))) || 0,
    action: String(_first(record, ['action', 'action_label', 'summary', 'description'], '') || ''),
    status,
    riskLevel,
    riskLabel: riskLabel(riskLevel),
    reason: String(_first(record, ['approval_reason', 'reason', 'policy_reason'], '') || ''),
    sessionId,
    conversationTitle: String(
      _first(record, ['conversation_title', 'session_title'], _first(conversation, ['title', 'name'], ''))
        || 'Requesting conversation',
    ),
    affectedRecords: records,
    expiresAt: _first(record, ['expires_at', 'expiration_time', 'expiry'], null),
    createdAt: _first(record, ['created_at', 'requested_at'], null),
    updatedAt: _first(record, ['updated_at'], null),
    decidedAt: _first(record, ['decided_at', 'approved_at', 'rejected_at', 'execution_finished_at'], null),
    decidedBy: String(_first(record, ['decided_by', 'approved_by', 'rejected_by'], '') || ''),
    decisionReason: String(_first(record, ['decision_reason', 'rejection_reason'], '') || ''),
    origin: String(_first(record, ['origin', 'surface'], '') || ''),
    result: _jsonValue(_first(record, ['result', 'result_json'], null), null),
    error: String(_first(record, ['error'], '') || ''),
    verificationStatus: String(_first(record, ['verification_status'], '') || ''),
    approvalRuleId: String(_first(record, ['approval_rule_id'], '') || ''),
    alwaysAllowEligible:
      status === 'pending'
      && riskLevel > 0
      && riskLevel < 3
      && record.always_allow_eligible !== false,
    auditEvents: _arrayValue(_first(record, ['audit_events', 'events', 'history'], [])),
    raw: record,
  };
}

/** Build the endpoint-specific stale-write payload for one decision or edit. */
export function buildMutationBody(approval, kind, extras = {}) {
  const item = approval && approval.argumentsHash !== undefined
    ? approval
    : normalizeApproval(approval);
  const body = { revision: item.revision };
  if (kind === 'approve') {
    body.arguments_hash = item.argumentsHash;
    body.always_allow = extras.alwaysAllow === true;
  } else if (kind === 'reject' || kind === 'cancel') {
    const reason = String(extras.reason || '').trim();
    if (reason) body.reason = reason;
  } else if (kind === 'edit') {
    if (!_isObject(extras.arguments)) throw new TypeError('Edited arguments must be a JSON object.');
    body.arguments = extras.arguments;
  } else {
    throw new TypeError(`Unknown approval mutation: ${kind}`);
  }
  return body;
}

export function isExpired(approval, now = Date.now()) {
  const value = approval && approval.expiresAt !== undefined
    ? approval.expiresAt
    : normalizeApproval(approval).expiresAt;
  const expires = value ? Date.parse(value) : NaN;
  return Number.isFinite(expires) && expires <= now;
}
