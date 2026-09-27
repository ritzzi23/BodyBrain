import assert from 'node:assert/strict';
import test from 'node:test';
import { CHAT_HISTORY_KEY, MAX_HISTORY_EXCHANGES, loadHistory, saveHistory, pruneHistory } from './chat-history.ts';

const store = () => {
  const entries = new Map();
  return { getItem: key => entries.get(key) ?? null, setItem: (key, value) => entries.set(key, value), removeItem: key => entries.delete(key) };
};
const source = 'No fracture of the right femur.';
const record = {
  id: 'record-1', title: 'Report', status: 'approved', event_date: '2026-09-27',
  pages: [{ page: 1, text: source }], findings: [{ approved: true, page: 1, quote: source }],
};
const conversation = () => ({
  question: 'What did the report say?', scopeName: 'Right femur',
  response: {
    answer: source, retrieval_mode: 'cognee', warnings: [], concepts: [], workflow_run_id: null, agent_task_id: null,
    citations: [{ record_id: record.id, title: record.title, page: 1, quote: source, event_date: record.event_date }],
  },
});

test('a fresh view restores exact questions, scopes and source quotations, and clear persists', () => {
  const storage = store();
  const original = [conversation()];
  assert.equal(saveHistory(storage, original), true);
  assert.deepEqual(loadHistory(storage), original);
  assert.equal(saveHistory(storage, []), true);
  assert.deepEqual(loadHistory(storage), []);
  assert.equal(storage.getItem(CHAT_HISTORY_KEY), null);
});

test('broken, incompatible and unavailable browser storage do not crash the workspace', () => {
  const storage = store();
  for (const value of ['{', 'null', '{"version":2,"exchanges":[]}', '{"version":1,"exchanges":[{"question":"Hi","response":{}}]}']) {
    storage.setItem(CHAT_HISTORY_KEY, value);
    assert.deepEqual(loadHistory(storage), []);
  }
  const blocked = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('quota'); }, removeItem() { throw new Error('blocked'); } };
  assert.deepEqual(loadHistory(blocked), []);
  assert.equal(saveHistory(blocked, [conversation()]), false);
  assert.equal(saveHistory(null, []), false);
});

test('history keeps the newest exchanges within its size budget without changing live state', () => {
  const storage = store();
  const original = Array.from({ length: MAX_HISTORY_EXCHANGES + 5 }, (_, i) => ({ ...conversation(), question: `Question ${i}` }));
  assert.equal(saveHistory(storage, original), true);
  assert.equal(original.length, MAX_HISTORY_EXCHANGES + 5);
  assert.equal(loadHistory(storage).length, MAX_HISTORY_EXCHANGES);
  assert.equal(loadHistory(storage)[0].question, 'Question 5');
  const enormous = conversation();
  enormous.response.answer = 'a'.repeat(1_500_001);
  assert.equal(saveHistory(storage, [enormous]), false);
  assert.deepEqual(loadHistory(storage), []);
});

test('failed storage updates clear older copies instead of retaining removed evidence', () => {
  const storage = store();
  saveHistory(storage, [conversation()]);
  storage.setItem = () => { throw new Error('quota'); };
  assert.equal(saveHistory(storage, [{ ...conversation(), question: 'Updated question' }]), false);
  assert.equal(storage.getItem(CHAT_HISTORY_KEY), null);
});

test('pending agent work restores as waiting and needs explicit refresh', () => {
  const storage = store();
  const item = conversation();
  item.agentStatus = 'pending';
  item.response.agent_task_id = 'task-1';
  saveHistory(storage, [item]);
  const restored = loadHistory(storage)[0];
  assert.equal(restored.agentStatus, 'waiting');
  assert.equal(restored.response.agent_task_id, 'task-1');
  assert.equal(item.agentStatus, 'pending');
});

test('deletion, supersession, revoked review and altered evidence remove the entire stale answer', () => {
  const exchanges = [conversation()];
  assert.equal(pruneHistory(exchanges, [record]), exchanges);
  for (const records of [[], [{ ...record, status: 'superseded' }], [{ ...record, status: 'deleting' }],
    [{ ...record, status: 'pending_review' }], [{ ...record, findings: [] }],
    [{ ...record, title: 'Changed title' }], [{ ...record, event_date: null }],
    [{ ...record, pages: [{ page: 1, text: 'A different source.' }] }]]) {
    assert.deepEqual(pruneHistory(exchanges, records), []);
  }
  const twoSources = conversation();
  twoSources.response.citations.push({ ...twoSources.response.citations[0], record_id: 'deleted-second-record' });
  assert.deepEqual(pruneHistory([twoSources], [record]), []);
  const noEvidence = conversation();
  noEvidence.response.citations = [];
  const uncited = [noEvidence];
  assert.equal(pruneHistory(uncited, []), uncited);
});
