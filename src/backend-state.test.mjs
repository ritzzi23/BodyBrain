import assert from 'node:assert/strict';
import test from 'node:test';
import { agentCapabilities, applyAgentResults, hasBackgroundWork } from './backend-state.ts';

test('independent ClawMax workflows work only with callbacks and retain legacy health compatibility', () => {
  assert.deepEqual(agentCapabilities({ configured: false, ingestion_configured: true, evidence_configured: false, callbacks_configured: true }), { ingestion: true, evidence: false });
  assert.deepEqual(agentCapabilities({ configured: false, ingestion_configured: false, evidence_configured: true, callbacks_configured: true }), { ingestion: false, evidence: true });
  assert.deepEqual(agentCapabilities({ configured: true, ingestion_configured: true, evidence_configured: true, callbacks_configured: false }), { ingestion: false, evidence: false });
  assert.deepEqual(agentCapabilities({ configured: true }), { ingestion: true, evidence: true });
  assert.deepEqual(agentCapabilities({ configured: false }), { ingestion: false, evidence: false });
  assert.deepEqual(agentCapabilities(), { ingestion: false, evidence: false });
});

const exchange = (taskId, question = taskId) => ({
  question,
  scopeName: 'left knee',
  agentStatus: 'pending',
  response: {
    answer: 'Original local evidence', citations: [{ record_id: 'source', quote: 'Exact source passage' }],
    concepts: [], retrieval_mode: 'local_evidence', warnings: [], agent_task_id: taskId,
  },
});

test('human review alone does not keep background polling alive after extraction', () => {
  const records = [{ status: 'pending_review', memory_status: 'not_indexed' }];
  assert.equal(hasBackgroundWork(records, [{ status: 'completed' }, { status: 'awaiting_review' }]), false);
  assert.equal(hasBackgroundWork(records, [{ status: 'submitted' }]), true);
  assert.equal(hasBackgroundWork(records, [{ status: 'running' }]), true);
  assert.equal(hasBackgroundWork([{ memory_status: 'pending' }], [{ status: 'completed' }]), true);
});

test('an older question can finish after a newer one without changing either question or scope', () => {
  const oldQuestion = exchange('older', 'What did the first report say?');
  const newQuestion = exchange('newer', 'What changed?');
  const result = { answer: 'Verified earlier passage', citations: [{ record_id: 'source', quote: 'Verified earlier passage' }], verification: 'exact_source_quotes' };
  const updated = applyAgentResults([oldQuestion, newQuestion], [{ id: 'older', status: 'completed', result }]);
  assert.equal(updated[0].agentStatus, 'completed');
  assert.equal(updated[0].response.answer, result.answer);
  assert.equal(updated[0].question, oldQuestion.question);
  assert.equal(updated[0].scopeName, 'left knee');
  assert.equal(updated[1], newQuestion);
  assert.equal(oldQuestion.agentStatus, 'pending');
});

test('invalid agent output preserves the original evidence while valid sibling tasks still complete', () => {
  const first = exchange('bad');
  const second = exchange('good');
  const updated = applyAgentResults([first, second], [
    { id: 'bad', status: 'completed', result: { answer: 'Unverified prose', citations: [] } },
    { id: 'good', status: 'completed', result: { answer: 'Verified quote', citations: [], verification: 'exact_source_quotes' } },
  ]);
  assert.equal(updated[0].agentStatus, 'failed');
  assert.equal(updated[0].response, first.response);
  assert.equal(updated[1].agentStatus, 'completed');
});
