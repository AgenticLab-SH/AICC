const secretKey = /(authorization|api[-_]?key|access[-_]?token|refresh[-_]?token|password|secret|credential|cookie)/i;
const bearer = /\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi;
const tokenAssignment = /((?:api[-_]?key|access[-_]?token|refresh[-_]?token|password|secret)\s*[=:]\s*)[^\s,;]+/gi;

export function redactText(value) {
  return String(value ?? '')
    .replace(bearer, 'Bearer <redacted>')
    .replace(tokenAssignment, '$1<redacted>');
}

export function sanitize(value, seen = new WeakSet()) {
  if (typeof value === 'string') return redactText(value);
  if (value === null || typeof value !== 'object') return value;
  if (seen.has(value)) return '<circular>';
  seen.add(value);
  if (Array.isArray(value)) return value.map(item => sanitize(item, seen));

  const output = {};
  for (const [key, item] of Object.entries(value)) {
    output[key] = secretKey.test(key) ? '<redacted>' : sanitize(item, seen);
  }
  return output;
}
