/** Settle the visual state of an agent tool explicitly cancelled by the user. */

export function cancelledToolLabel(toolName, currentLabel) {
  const tool = String(toolName || '').toLowerCase();
  if (tool === 'bash') return 'Bash';
  if (tool === 'python') return 'Python';
  return currentLabel || 'Tool';
}

export function settleCancelledToolNode(node) {
  if (!node) return;

  if (node._waveInterval) {
    clearInterval(node._waveInterval);
    node._waveInterval = null;
  }
  if (node._elapsedTicker) {
    clearInterval(node._elapsedTicker);
    node._elapsedTicker = null;
  }

  node.classList.remove('running');
  node.classList.add('cancelled');

  const wave = node.querySelector('.agent-thread-wave');
  if (wave) wave.textContent = '';

  const icon = node.querySelector('.agent-thread-icon');
  if (icon) icon.textContent = '\u25A0';

  const toolLabel = node.querySelector('.agent-thread-tool');
  if (toolLabel) {
    toolLabel.textContent = cancelledToolLabel(
      node.dataset && node.dataset.tool,
      toolLabel.textContent,
    );
  }

  let status = node.querySelector('.agent-thread-status');
  if (!status) {
    status = document.createElement('span');
    status.className = 'agent-thread-status';
    const header = node.querySelector('.agent-thread-header');
    if (header) header.appendChild(status);
  }
  if (status) status.textContent = 'cancelled';
}
