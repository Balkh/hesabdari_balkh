import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('frontend foundation has bilingual and directional architecture', async () => {
  const source = await readFile(new URL('../src/i18n/translations.ts', import.meta.url), 'utf8');
  assert.match(source, /fa:/);
  assert.match(source, /en:/);
  assert.match(source, /rtl/);
  assert.match(source, /ltr/);
});
