import type { Concept } from './anatomy/anatomy';

export interface Finding {
  id: string;
  quote: string;
  page: number;
  anatomy_query: string;
  concept: Concept | null;
  mapping_status: 'matched' | 'unmapped';
  laterality: string | null;
  approved?: boolean;
}

export interface BodyRecord {
  id: string;
  title: string;
  record_type: string;
  event_date: string | null;
  status: 'pending_review' | 'approved' | 'superseded' | 'deleting';
  memory_status: 'not_indexed' | 'pending' | 'indexed' | 'failed' | 'unconfigured' | 'retired';
  text: string;
  pages: { page: number; text: string }[];
  findings: Finding[];
  created_at: string;
  warnings: string[];
  revision_number?: number;
  revises_record_id?: string | null;
  superseded_by?: string | null;
  deletion_error?: string | null;
  source_kind?: 'original' | 'corrected_transcription';
  dataset_source?: { dataset: string; subject_id: string; archive_sha256: string; transformation: string };
}

export interface RecordRevision {
  title: string;
  text: string;
  record_type: string;
  event_date: string | null;
}

export interface Health {
  status: string;
  workspace_label?: string;
  integrations: {
    cognee: { configured: boolean; mode: string };
    clawmax: { configured: boolean; transport?: 'dashboard' | 'cognee_relay'; ingestion_configured?: boolean; evidence_configured?: boolean; callbacks_configured?: boolean };
  };
  counts: { records: number; approved: number };
}

export interface IntegrationStatus {
  cognee: { configured: boolean; reachable?: boolean; message?: string };
  clawmax: { ingestion: { status: string; worker_online?: boolean; worker_state?: string; message?: string; checked_at?: string } };
}

export interface Citation {
  record_id: string;
  title: string;
  page: number;
  quote: string;
  event_date: string | null;
}

export interface Answer {
  answer: string;
  citations: Citation[];
  concepts: Concept[];
  retrieval_mode: 'cognee' | 'local_evidence';
  warnings: string[];
  workflow_run_id?: string | null;
  agent_task_id?: string | null;
}

export interface AgentTask {
  id: string;
  status: 'pending' | 'completed' | 'failed';
  result: { answer?: string; citations?: Citation[]; concepts?: Concept[]; verification?: string } | null;
}

export interface WorkflowRun {
  id: string;
  kind: string;
  status: string;
  created_at: string;
  steps: { name: string; status: string; detail?: string }[];
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 120_000);
  try {
    const response = await fetch(`/api${path}`, { ...init, signal: controller.signal });
    const contentType = response.headers.get('content-type') ?? '';
    if (!contentType.includes('application/json')) {
      throw new Error('The backend is unavailable. Start it with npm run backend, then reconnect.');
    }
    const body = await response.json();
    if (!response.ok) {
      const detail = typeof body.detail === 'string' ? body.detail : typeof body.error === 'string' ? body.error : `Request failed (${response.status}).`;
      throw new Error(detail);
    }
    return body as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw new Error('This request timed out. Refresh the records before trying again.');
    if (error instanceof TypeError) throw new Error('Cannot reach the backend. Start it with npm run backend, then reconnect.');
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export const backend = {
  health: () => request<Health>('/health'),
  integrations: () => request<IntegrationStatus>('/integrations'),
  retention: (days: number, apply = false) => request<{ tasks: number; activity_entries: number }>('/history/retention', json({ older_than_days: days, apply })),
  addNote: (clientId: string, text: string, conceptId: string, eventDate: string) => request<BodyRecord>('/notes', json({ client_id: clientId, text, concept_id: conceptId, event_date: eventDate })),
  records: () => request<{ records: BodyRecord[] }>('/records'),
  record: (id: string) => request<BodyRecord>(`/records/${encodeURIComponent(id)}`),
  revise: (id: string, revision: RecordRevision) => request<BodyRecord>(`/records/${encodeURIComponent(id)}/revisions`, json(revision)),
  deleteRecord: (id: string) => request<{ status: 'deleted'; record_id: string }>(`/records/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  upload: (file: File, title: string, recordType: string, eventDate?: string, allowAgent = false) => {
    const data = new FormData();
    data.append('file', file);
    if (title.trim()) data.append('title', title.trim());
    data.append('record_type', recordType);
    if (eventDate) data.append('event_date', eventDate);
    data.append('allow_agent', String(allowAgent));
    return request<BodyRecord>('/records', { method: 'POST', body: data });
  },
  addText: (title: string, text: string, recordType: string, eventDate?: string, allowAgent = false) => request<BodyRecord>('/records/text', json({ title, text, record_type: recordType, event_date: eventDate || null, allow_agent: allowAgent })),
  approve: (id: string, findingIds: string[]) => request<BodyRecord>(`/records/${encodeURIComponent(id)}/approve`, json({ finding_ids: findingIds })),
  index: (id: string) => request<BodyRecord>(`/records/${encodeURIComponent(id)}/index`, { method: 'POST' }),
  timeline: (conceptId?: string) => request<{ events: BodyRecord[] }>(`/timeline${conceptId ? `?concept_id=${encodeURIComponent(conceptId)}` : ''}`),
  chat: (question: string, conceptId?: string, allowAgent = false) => request<Answer>('/chat', json({ question, concept_id: conceptId || null, allow_agent: allowAgent })),
  demo: (allowAgent = false) => request<{ records: BodyRecord[] }>(`/demo?allow_agent=${allowAgent}`, { method: 'POST' }),
  runs: () => request<{ runs: WorkflowRun[] }>('/runs'),
  task: (id: string) => request<AgentTask>(`/tasks/${encodeURIComponent(id)}`),
  anatomy: (query: string) => request<{ concepts: Concept[] }>(`/anatomy/search?q=${encodeURIComponent(query)}`),
  remap: (recordId: string, findingId: string, conceptId: string | null) => request<BodyRecord>(`/records/${encodeURIComponent(recordId)}/mapping`, { ...json({ finding_id: findingId, concept_id: conceptId }), method: 'PATCH' }),
  sourceUrl: (id: string) => `/api/records/${encodeURIComponent(id)}/source`,
};
