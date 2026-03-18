export function formatTokens(n) {
  if (n === 0) return '—';
  if (n < 1000) return String(n);
  const k = n / 1000;
  if (k >= 10) return `${Math.round(k)}k`;
  return `${k.toFixed(1)}k`;
}

export function formatElapsed(ms) {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
}

export function shortenModel(model) {
  if (!model) return '—';
  const parts = model.split('/');
  const name = parts[parts.length - 1] ?? model;
  return name.replace(/^claude-/, '');
}
