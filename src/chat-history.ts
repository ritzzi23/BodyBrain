import type { BodyRecord, Citation } from './backend-api';
import type { Exchange } from './backend-state';

export const CHAT_HISTORY_KEY = 'bodybrain.chat.v1';
export const MAX_HISTORY_EXCHANGES = 40;
const MAX_HISTORY_CHARACTERS = 1_500_000;
type HistoryStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | null | undefined;
type ObjectValue = Record<string, unknown>;

function object(value: unknown): value is ObjectValue {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function citation(value: unknown): value is Citation {
  return object(value) && typeof value.record_id === 'string' && typeof value.title === 'string'
    && Number.isInteger(value.page) && (value.page as number) > 0
    && typeof value.quote === 'string' && value.quote.trim().length > 0
    && (value.event_date === null || typeof value.event_date === 'string');
}

function exchange(value: unknown): value is Exchange {
  if (!object(value) || typeof value.question !== 'string' || !value.question.trim()
    || value.question.length > 2000 || !object(value.response)) return false;
  if (value.scopeName !== undefined && typeof value.scopeName !== 'string') return false;
  if (value.agentStatus !== undefined && !['pending', 'completed', 'failed', 'waiting'].includes(String(value.agentStatus))) return false;
  const response = value.response;
  return typeof response.answer === 'string'
    && ['cognee', 'local_evidence'].includes(String(response.retrieval_mode))
    && Array.isArray(response.citations) && response.citations.every(citation)
    && Array.isArray(response.warnings) && response.warnings.every(item => typeof item === 'string')
    && Array.isArray(response.concepts) && response.concepts.every(item => object(item)
      && typeof item.id === 'string' && typeof item.name === 'string'
      && Array.isArray(item.elements) && item.elements.every(id => typeof id === 'string'))
    && (response.agent_task_id === undefined || response.agent_task_id === null || typeof response.agent_task_id === 'string')
    && (response.workflow_run_id === undefined || response.workflow_run_id === null || typeof response.workflow_run_id === 'string');
}

/** Storage can be blocked by browser settings or contain obsolete/malformed data. */
export function loadHistory(storage: HistoryStorage): Exchange[] {
  try {
    const raw = storage?.getItem(CHAT_HISTORY_KEY);
    if (!raw || raw.length > MAX_HISTORY_CHARACTERS) return [];
    const saved: unknown = JSON.parse(raw);
    if (!object(saved) || saved.version !== 1 || !Array.isArray(saved.exchanges)) return [];
    return saved.exchanges.filter(exchange).slice(-MAX_HISTORY_EXCHANGES).map(item =>
      item.agentStatus === 'pending' ? { ...item, agentStatus: 'waiting' } : item);
  } catch {
    return [];
  }
}

/** Keep recent conversations bounded; never let a storage failure break chat. */
export function saveHistory(storage: HistoryStorage, exchanges: Exchange[]): boolean {
  if (!storage) return false;
  try {
    if (exchanges.length === 0) {
      storage.removeItem(CHAT_HISTORY_KEY);
      return true;
    }
    const recent = exchanges.slice(-MAX_HISTORY_EXCHANGES);
    let serialized = JSON.stringify({ version: 1, exchanges: recent });
    while (serialized.length > MAX_HISTORY_CHARACTERS && recent.length > 0) {
      recent.shift();
      serialized = JSON.stringify({ version: 1, exchanges: recent });
    }
    if (!recent.length) {
      storage.removeItem(CHAT_HISTORY_KEY);
      return false;
    }
    storage.setItem(CHAT_HISTORY_KEY, serialized);
    return true;
  } catch {
    // Avoid retaining old source text when a deletion/correction cannot be saved.
    try { storage.removeItem(CHAT_HISTORY_KEY); } catch { /* Storage is unavailable. */ }
    return false;
  }
}

/** Remove the full answer if any of its supporting evidence is no longer active. */
export function pruneHistory(exchanges: Exchange[], records: BodyRecord[]): Exchange[] {
  const active = new Map(records.filter(record => record.status === 'approved').map(record => [record.id, record]));
  const filtered = exchanges.filter(item => item.response.citations.every(cite => {
    const record = active.get(cite.record_id);
    return record && cite.title === record.title && cite.event_date === record.event_date
      && record.findings.some(finding => finding.approved === true && finding.page === cite.page && finding.quote === cite.quote)
      && record.pages.some(page => page.page === cite.page && page.text.includes(cite.quote));
  }));
  return filtered.length === exchanges.length ? exchanges : filtered;
}
