import type { AgentTask, Answer, BodyRecord, Health, WorkflowRun } from './backend-api';

export function agentCapabilities(provider?: Health['integrations']['clawmax']) {
  const callbacks = provider?.callbacks_configured ?? provider?.configured ?? false;
  return {
    ingestion: callbacks && (provider?.ingestion_configured ?? provider?.configured ?? false),
    evidence: callbacks && (provider?.evidence_configured ?? provider?.configured ?? false),
  };
}

export type Exchange = {
  question: string;
  response: Answer;
  scopeName?: string;
  agentStatus?: 'pending' | 'completed' | 'failed' | 'waiting';
};

export function hasBackgroundWork(records: Pick<BodyRecord, 'memory_status'>[], runs: Pick<WorkflowRun, 'status'>[]) {
  return records.some(record => record.memory_status === 'pending')
    || runs.some(run => ['submitted', 'running'].includes(run.status));
}

/** Apply each independent task without replacing other conversations or unverified evidence. */
export function applyAgentResults(exchanges: Exchange[], tasks: AgentTask[]): Exchange[] {
  return exchanges.map(exchange => {
    const task = tasks.find(item => item.id === exchange.response.agent_task_id);
    if (!task || exchange.agentStatus !== 'pending') return exchange;
    if (task.status === 'failed') return { ...exchange, agentStatus: 'failed' };
    if (task.status !== 'completed') return exchange;
    const result = task.result;
    if (result?.verification !== 'exact_source_quotes' || !result.answer || !result.citations) {
      return { ...exchange, agentStatus: 'failed' };
    }
    return {
      ...exchange,
      agentStatus: 'completed',
      response: { ...exchange.response, answer: result.answer, citations: result.citations, concepts: result.concepts ?? [] },
    };
  });
}
