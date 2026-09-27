import assert from 'node:assert/strict';
import test from 'node:test';
import { backend } from './backend-api.ts';

test('record dates, anatomy scope and explicit agent consent survive the browser API boundary', async t => {
  const calls = [];
  const originalWindow = globalThis.window;
  globalThis.window = { setTimeout, clearTimeout };
  t.after(() => { if (originalWindow === undefined) delete globalThis.window; else globalThis.window = originalWindow; });
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, ...options });
    return Response.json({});
  });

  await backend.upload(new File(['Example report'], 'report.txt'), 'Report', 'medical_report', '2026-09-27');
  assert.equal(calls.at(-1).body.get('event_date'), '2026-09-27');
  assert.equal(calls.at(-1).body.get('allow_agent'), 'false');
  await backend.upload(new File(['Example report'], 'report.txt'), '', 'medical_report', '2026-09-26', true);
  assert.equal(calls.at(-1).body.get('allow_agent'), 'true');

  await backend.addText('Report', 'Example report', 'medical_report', '2026-09-27');
  assert.equal(JSON.parse(calls.at(-1).body).allow_agent, false);
  await backend.addText('Report', 'Example report', 'medical_report', '2026-09-27', true);
  assert.equal(JSON.parse(calls.at(-1).body).allow_agent, true);

  await backend.chat('What changed?', 'FMA:123', true);
  assert.deepEqual(JSON.parse(calls.at(-1).body), { question: 'What changed?', concept_id: 'FMA:123', allow_agent: true });
  await backend.chat('What changed?');
  assert.deepEqual(JSON.parse(calls.at(-1).body), { question: 'What changed?', concept_id: null, allow_agent: false });
  await backend.timeline('FMA:123');
  assert.equal(calls.at(-1).url, '/api/timeline?concept_id=FMA%3A123');
  await backend.timeline();
  assert.equal(calls.at(-1).url, '/api/timeline');
  await backend.demo();
  assert.equal(calls.at(-1).url, '/api/demo?allow_agent=false');
  await backend.demo(true);
  assert.equal(calls.at(-1).url, '/api/demo?allow_agent=true');
});

test('corrections preserve exact source text and send version metadata through the revisions endpoint', async t => {
  const originalWindow = globalThis.window;
  globalThis.window = { setTimeout, clearTimeout };
  t.after(() => { if (originalWindow === undefined) delete globalThis.window; else globalThis.window = originalWindow; });
  const revision = { title: 'Corrected knee report', text: '  Left knee finding.\r\n\nFollow-up:\tstable.  ', record_type: 'clinical_note', event_date: null };
  const draft = { id: 'draft', status: 'pending_review', revision_number: 2, revises_record_id: 'source/id', source_kind: 'corrected_transcription', ...revision };
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/records/source%2Fid/revisions');
    assert.equal(options.method, 'POST');
    assert.equal(options.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(options.body), revision);
    return Response.json(draft, { status: 201 });
  });
  assert.deepEqual(await backend.revise('source/id', revision), draft);
});

test('deletion exposes cleanup errors and retries the same specific record without deleting other versions', async t => {
  const originalWindow = globalThis.window;
  globalThis.window = { setTimeout, clearTimeout };
  t.after(() => { if (originalWindow === undefined) delete globalThis.window; else globalThis.window = originalWindow; });
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, method: options.method });
    if (calls.length === 1) return Response.json({ detail: 'Cognee cleanup failed. Retry deletion.' }, { status: 503 });
    return Response.json({ status: 'deleted', record_id: 'record/one' });
  });
  await assert.rejects(backend.deleteRecord('record/one'), /Cognee cleanup failed\. Retry deletion\./);
  assert.deepEqual(await backend.deleteRecord('record/one'), { status: 'deleted', record_id: 'record/one' });
  assert.deepEqual(calls, [
    { url: '/api/records/record%2Fone', method: 'DELETE' },
    { url: '/api/records/record%2Fone', method: 'DELETE' },
  ]);
});
