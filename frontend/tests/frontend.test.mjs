import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('frontend foundation has bilingual and directional architecture', async () => {
  const source = await read('../src/i18n/translations.ts');
  assert.match(source, /fa:/);
  assert.match(source, /en:/);
  assert.match(source, /rtl/);
  assert.match(source, /ltr/);
});

test('design system exposes shared primitives and tokens', async () => {
  const exports = await read('../src/components/index.ts');
  const tokens = await read('../src/theme/tokens.ts');
  assert.match(exports, /Button/);
  assert.match(exports, /Card/);
  assert.match(exports, /StatusBadge/);
  assert.match(tokens, /colors/);
  assert.match(tokens, /spacing/);
  assert.match(tokens, /radius/);
});

test('api client uses relative api boundary and structured errors', async () => {
  const source = await read('../src/services/api.ts');
  assert.match(source, /\/api\/v1/);
  assert.match(source, /response\.ok/);
  assert.match(source, /ApiError/);
});

test('application shell defines route boundary and avoids business workflows', async () => {
  const source = await read('../src/app/App.tsx');
  assert.match(source, /BrowserRouter/);
  assert.match(source, /Routes/);
  assert.match(source, /path="\/"/);
  assert.match(source, /path="\/about"/);
});
