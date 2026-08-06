import assert from 'node:assert/strict';
import test from 'node:test';
import { redactText, sanitize } from '../src/lib/redact.mjs';

test('sanitize removes common secret fields recursively', () => {
  const value = sanitize({ apiKey: 'abc', nested: { refresh_token: 'def', label: 'safe' } });
  assert.deepEqual(value, { apiKey: '<redacted>', nested: { refresh_token: '<redacted>', label: 'safe' } });
});

test('redactText removes bearer values and assignments', () => {
  const text = redactText('Authorization: Bearer abc.def api_key=secret-value');
  assert.doesNotMatch(text, /abc\.def|secret-value/);
});
