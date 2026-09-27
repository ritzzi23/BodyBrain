import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Activity, ArrowLeft, ArrowRight, Bot, Check, CheckCheck, ChevronRight, Clock3, Database, FileText, Focus, History, LoaderCircle, MessageCircle, Pencil, Plus, RefreshCw, Send, ShieldCheck, Trash2, Upload, X } from 'lucide-react';
import type { Concept } from './anatomy/anatomy';
import { backend, type BodyRecord, type Citation, type Health, type WorkflowRun } from './backend-api';
import { agentCapabilities, applyAgentResults, hasBackgroundWork, type Exchange } from './backend-state';
import { loadHistory, pruneHistory, saveHistory } from './chat-history';
import './backend.css';

type Tab = 'records' | 'ask' | 'timeline' | 'activity';
const tabs = [{ id: 'records', name: 'Records', icon: FileText }, { id: 'ask', name: 'Ask your records', icon: MessageCircle }, { id: 'timeline', name: 'Timeline', icon: Clock3 }, { id: 'activity', name: 'Activity', icon: Activity }] as const;
const statusLabels: Record<BodyRecord['status'], string> = { pending_review: 'Needs review', approved: 'Reviewed', superseded: 'Superseded', deleting: 'Deletion pending' };
const memoryLabels: Record<BodyRecord['memory_status'], string> = { not_indexed: 'Awaiting review', pending: 'Saving to Cognee…', indexed: 'In Cognee memory', failed: 'Cognee indexing failed', unconfigured: 'Local evidence saved', retired: 'Removed from Cognee' };
const formatDate = (date: string | null) => date ? new Date(date.length === 10 ? `${date}T12:00:00` : date).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : 'Date not provided';
const readable = (text: string) => text.replaceAll('_', ' ');

function Notices({ messages }: { messages: string[] }) {
  const visible = messages.filter(message => !/^ClawMax is (?:not configured|not available for new requests)\b/i.test(message));
  return visible.length ? <div className="backend-notices">{visible.map((message, i) => <p key={`${i}:${message}`}>{message}</p>)}</div> : null;
}

function recordVersions(records: BodyRecord[], selected?: BodyRecord) {
  if (!selected) return [];
  const ids = new Set([selected.id]);
  let previousSize = 0;
  while (previousSize !== ids.size) {
    previousSize = ids.size;
    for (const record of records) {
      if (ids.has(record.id) || (record.revises_record_id && ids.has(record.revises_record_id)) || (record.superseded_by && ids.has(record.superseded_by))) {
        ids.add(record.id);
        if (record.revises_record_id) ids.add(record.revises_record_id);
        if (record.superseded_by) ids.add(record.superseded_by);
      }
    }
  }
  return records.filter(record => ids.has(record.id)).sort((a, b) => (a.revision_number ?? 1) - (b.revision_number ?? 1));
}

function SourceCitations({ citations, onOpen }: { citations: Citation[]; onOpen: (id: string) => void }) {
  return <div className="backend-citations">{citations.map((citation, i) => <button key={`${citation.record_id}:${i}`} onClick={() => onOpen(citation.record_id)}><span className="backend-citation-number">{i + 1}</span><span><strong>{citation.title}</strong><small>Page {citation.page} · {formatDate(citation.event_date)}</small><q>{citation.quote}</q></span><ChevronRight size={14} /></button>)}</div>;
}

function AgentConsent({ checked, onChange, children, disabled }: { checked: boolean; onChange: (value: boolean) => void; children: string; disabled: boolean }) {
  return <label className="backend-agent-consent"><input type="checkbox" checked={checked} disabled={disabled} onChange={event => onChange(event.target.checked)} /><span>{children}</span></label>;
}

export default function BackendPanel({ open, selectedConcept, onClose, onSelectConcept }: { open: boolean; selectedConcept: Concept | null; onClose: () => void; onSelectConcept: (concept: Concept) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const alive = useRef(true);
  const [tab, setTab] = useState<Tab>('records');
  const [health, setHealth] = useState<Health | null>(null);
  const agent = agentCapabilities(health?.integrations.clawmax);
  const agentUsesRelay = health?.integrations.clawmax.transport === 'cognee_relay';
  const agentRoute = agentUsesRelay ? ' through Cognee' : '';
  const [records, setRecords] = useState<BodyRecord[]>([]);
  const recordsRef = useRef<BodyRecord[] | null>(null);
  const [events, setEvents] = useState<BodyRecord[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [findingIds, setFindingIds] = useState<string[]>([]);
  const [reviewTab, setReviewTab] = useState<'findings' | 'source'>('findings');
  const [adding, setAdding] = useState(false);
  const [correctionId, setCorrectionId] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [inputMode, setInputMode] = useState<'file' | 'text'>('file');
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [recordType, setRecordType] = useState('medical_report');
  const [eventDate, setEventDate] = useState('');
  const [recordText, setRecordText] = useState('');
  const [allowImportAgent, setAllowImportAgent] = useState(false);
  const [allowChatAgent, setAllowChatAgent] = useState(false);
  const [allowDemoAgent, setAllowDemoAgent] = useState(false);
  const [excludedScopeId, setExcludedScopeId] = useState<string | null>(null);
  const scopedConcept = selectedConcept?.id !== excludedScopeId ? selectedConcept : null;
  const scopeId = scopedConcept?.id;
  const scopeRef = useRef(scopeId);
  scopeRef.current = scopeId;
  const refreshVersion = useRef(0);
  const [question, setQuestion] = useState('');
  const [exchanges, setExchanges] = useState<Exchange[]>(() => {
    try { return loadHistory(window.localStorage); } catch { return []; }
  });
  const [historySaved, setHistorySaved] = useState(true);
  const [busy, setBusy] = useState('connecting');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [pollStopped, setPollStopped] = useState(false);
  const [mappingFindingId, setMappingFindingId] = useState<string | null>(null);
  const [mappingQuery, setMappingQuery] = useState('');
  const [mappingResults, setMappingResults] = useState<Concept[]>([]);
  const [mappingSearching, setMappingSearching] = useState(false);
  const selected = records.find(record => record.id === selectedId);
  const correction = records.find(record => record.id === correctionId);
  const versions = recordVersions(records, selected);
  const pendingCorrection = selected && records.find(record => record.revises_record_id === selected.id && record.status === 'pending_review');

  useEffect(() => {
    try { setHistorySaved(saveHistory(window.localStorage, exchanges)); }
    catch { setHistorySaved(false); }
  }, [exchanges]);

  const refresh = useCallback(async () => {
    const requestedScope = scopeRef.current;
    const version = ++refreshVersion.current;
    const [nextHealth, nextRecords, nextEvents, nextRuns] = await Promise.all([backend.health(), backend.records(), backend.timeline(requestedScope), backend.runs()]);
    const pending = hasBackgroundWork(nextRecords.records, nextRuns.runs);
    if (alive.current && version === refreshVersion.current) {
      setHealth(nextHealth); setRecords(nextRecords.records); setRuns(nextRuns.runs);
      recordsRef.current = nextRecords.records;
      setSelectedId(previous => previous && nextRecords.records.some(record => record.id === previous) ? previous : null);
      setExchanges(previous => pruneHistory(previous, nextRecords.records));
      if (scopeRef.current === requestedScope) setEvents(nextEvents.events);
    }
    return pending;
  }, []);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const element = dialog.current;
    if (!element?.open) element?.showModal();
    return () => { element?.close(); if (previouslyFocused?.isConnected) previouslyFocused.focus(); };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setEvents([]);
    const version = refreshVersion.current + 1;
    void refresh().catch(reason => {
      if (alive.current && version === refreshVersion.current) setError(reason instanceof Error ? reason.message : 'Could not load records.');
    }).finally(() => {
      // Closing the dialog must not strand a finished initial request in "connecting".
      if (alive.current && version === refreshVersion.current) setBusy(current => current === 'connecting' ? '' : current);
    });
  }, [open, scopeId, refresh]);

  const hasPending = hasBackgroundWork(records, runs);
  useEffect(() => {
    if (!hasPending || pollStopped) return;
    let cancelled = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const stillPending = await refresh();
        if (cancelled || !stillPending) return;
        attempts += 1;
        if (!cancelled && attempts < 60) timer = setTimeout(poll, 2000);
        if (attempts >= 60 && !cancelled) { setPollStopped(true); setNotice('Background work is still pending. Refresh to check its progress.'); }
      } catch (reason) {
        if (!cancelled) { setPollStopped(true); setError(reason instanceof Error ? reason.message : 'Could not refresh indexing status.'); }
      }
    };
    timer = setTimeout(poll, 2000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [hasPending, pollStopped, refresh]);

  const pendingAgentIds = exchanges.filter(exchange => exchange.agentStatus === 'pending').map(exchange => exchange.response.agent_task_id).filter(Boolean).join(',');
  useEffect(() => {
    if (!pendingAgentIds) return;
    let cancelled = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const results = await Promise.all(pendingAgentIds.split(',').map(id => backend.task(id)));
        if (cancelled || !alive.current) return;
        setExchanges(previous => {
          const updated = applyAgentResults(previous, results);
          return recordsRef.current ? pruneHistory(updated, recordsRef.current) : updated;
        });
        attempts += 1;
        if (attempts < 60 && results.some(task => task.status === 'pending')) timer = setTimeout(poll, 2000);
        else if (attempts >= 60) setExchanges(previous => previous.map(exchange => exchange.agentStatus === 'pending' ? { ...exchange, agentStatus: 'waiting' } : exchange));
      } catch {
        if (!cancelled && alive.current) setExchanges(previous => previous.map(exchange => exchange.agentStatus === 'pending' ? { ...exchange, agentStatus: 'waiting' } : exchange));
      }
    };
    timer = setTimeout(poll, 1000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [pendingAgentIds]);

  const selectedFindingsKey = selected?.status === 'pending_review' ? `${selected.id}:${selected.findings.map(finding => finding.id).sort().join(',')}` : '';
  useEffect(() => {
    if (selected?.status === 'pending_review') setFindingIds(selected.findings.map(finding => finding.id));
    // Polling preserves a review selection unless the selected record or extracted IDs change.
  }, [selectedFindingsKey]);

  useEffect(() => {
    if (!mappingFindingId || !mappingQuery.trim()) { setMappingResults([]); setMappingSearching(false); return; }
    let cancelled = false;
    setMappingSearching(true);
    const timer = setTimeout(() => {
      void backend.anatomy(mappingQuery.trim()).then(result => { if (!cancelled) setMappingResults(result.concepts); }).catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : 'Could not search the atlas.'); }).finally(() => { if (!cancelled) setMappingSearching(false); });
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [mappingFindingId, mappingQuery]);

  function openRecord(record: BodyRecord) {
    setSelectedId(record.id); setFindingIds(record.findings.filter(finding => record.status === 'pending_review' || finding.approved !== false).map(finding => finding.id)); setReviewTab('findings'); setAdding(false); setCorrectionId(null); setDeleteConfirmId(null); setMappingFindingId(null); setTab('records');
  }

  function startImport() {
    setAdding(true); setSelectedId(null); setCorrectionId(null); setDeleteConfirmId(null);
    setTitle(''); setRecordText(''); setEventDate(''); setRecordType('medical_report'); setFile(null); setAllowImportAgent(false);
  }

  function startCorrection(record: BodyRecord) {
    setAdding(true); setCorrectionId(record.id); setDeleteConfirmId(null); setInputMode('text');
    setTitle(record.title); setRecordText(record.text); setEventDate(record.event_date ?? ''); setRecordType(record.record_type); setFile(null); setAllowImportAgent(false);
  }

  function selectConcept(concept: Concept) { onSelectConcept(concept); onClose(); }

  async function act(label: string, task: () => Promise<void>) {
    setBusy(label); setError(''); setNotice('');
    try { await task(); } catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : 'Something went wrong. Please try again.'); }
    finally { if (alive.current) setBusy(''); }
  }

  async function submitRecord(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submittedDate = new FormData(event.currentTarget).get('event_date');
    const submittedEventDate = typeof submittedDate === 'string' ? submittedDate : eventDate;
    setEventDate(submittedEventDate);
    await act('importing', async () => {
      const allowAgent = allowImportAgent && agent.ingestion;
      const record = correctionId
        ? await backend.revise(correctionId, { title: title.trim(), text: recordText, record_type: recordType, event_date: submittedEventDate || null })
        : inputMode === 'file' && file ? await backend.upload(file, title, recordType, submittedEventDate, allowAgent) : await backend.addText(title.trim(), recordText, recordType, submittedEventDate, allowAgent);
      const wasCorrection = !!correctionId;
      await refresh();
      if (!alive.current) return;
      setTitle(''); setRecordText(''); setEventDate(''); setFile(null); setAllowImportAgent(false); setPollStopped(false); openRecord(record); setNotice(wasCorrection ? 'Correction draft created. Review its findings and links. The current approved version remains in memory until you approve this draft.' : 'Record imported. Review the source and anatomical links before adding it to memory.');
    });
  }

  async function deleteRecord(record: BodyRecord) {
    await act('deleting', async () => {
      try { await backend.deleteRecord(record.id); }
      catch (reason) {
        // A failed remote cleanup leaves a durable retry state on the server.
        await refresh().catch(() => undefined);
        throw reason;
      }
      if (!alive.current) return;
      const remaining = (recordsRef.current ?? records).filter(item => item.id !== record.id);
      recordsRef.current = remaining;
      setRecords(remaining);
      setExchanges(previous => pruneHistory(previous, remaining));
      setSelectedId(null); setDeleteConfirmId(null); setCorrectionId(null); setAdding(false); setMappingFindingId(null);
      await refresh();
      if (alive.current) setNotice(`“${record.title}” was deleted, including its source and connected memory. Other versions are unchanged.`);
    });
  }

  async function approveRecord(record: BodyRecord) {
    await act('approving', async () => {
      let approved: BodyRecord;
      try { approved = await backend.approve(record.id, findingIds); }
      catch (reason) {
        await refresh().catch(() => undefined);
        throw reason;
      }
      if (!alive.current) return;
      const nextRecords = (recordsRef.current ?? records).map((item): BodyRecord => item.id === approved.id ? approved : item.id === approved.revises_record_id ? { ...item, status: 'superseded', superseded_by: approved.id, memory_status: 'retired' } : item);
      if (!nextRecords.some(item => item.id === approved.id)) nextRecords.push(approved);
      recordsRef.current = nextRecords;
      setRecords(nextRecords);
      setExchanges(previous => pruneHistory(previous, nextRecords));
      await refresh();
      if (alive.current) {
        setPollStopped(false);
        setNotice(approved.revises_record_id ? 'Correction approved. This version is now in memory; the previous source remains in version history.' : 'Review saved. This record is now available to your memory workflow.');
      }
    });
  }

  function clearHistory() {
    setExchanges([]);
    let cleared = false;
    try { cleared = saveHistory(window.localStorage, []); } catch { /* Chat remains usable without storage. */ }
    setHistorySaved(cleared);
    setNotice(cleared ? 'Conversation history cleared from this browser.' : 'Conversation cleared for this session. Browser storage could not be updated.');
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    const asked = question.trim();
    if (!asked) return;
    const askedScope = scopedConcept;
    await act('asking', async () => {
      const response = await backend.chat(asked, askedScope?.id, allowChatAgent && agent.evidence);
      if (!alive.current) return;
      setExchanges(previous => [...previous, { question: asked, response, scopeName: askedScope?.name, agentStatus: response.agent_task_id ? 'pending' : undefined }]); setQuestion(''); setAllowChatAgent(false); setPollStopped(false);
      await refresh();
    });
  }

  async function updateMapping(findingId: string, conceptId: string | null) {
    if (!selected) return;
    await act('mapping', async () => {
      const record = await backend.remap(selected.id, findingId, conceptId);
      if (!alive.current) return;
      setRecords(previous => previous.map(item => item.id === record.id ? record : item));
      setMappingFindingId(null);
      setNotice(conceptId ? 'Anatomical link updated. Review the finding before saving.' : 'Anatomical link removed. The source passage is preserved.');
    });
  }

  const openCitation = (id: string) => {
    const existing = records.find(record => record.id === id);
    if (existing) { openRecord(existing); setReviewTab('source'); return; }
    void act('loading', async () => { const record = await backend.record(id); if (alive.current) { setRecords(previous => [...previous.filter(item => item.id !== id), record]); openRecord(record); setReviewTab('source'); } });
  };

  return <dialog ref={dialog} className="backend-dialog" aria-labelledby="backend-heading" onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.currentTarget === event.target) onClose(); }}>
    <div className="backend-shell">
      <header className="backend-header"><div className="backend-heading-icon"><Database size={21} /></div><div><span className="eyebrow">BODYBRAIN MEMORY</span><h2 id="backend-heading">The story behind your anatomy.</h2></div><button className="icon-button" onClick={onClose} aria-label="Close records"><X size={20} /></button></header>
      <div className="backend-provider-strip"><span className={health ? 'online' : ''}><i />{health ? 'Backend connected' : busy === 'connecting' ? 'Connecting…' : 'Backend offline'}</span><span><Database size={12} />Cognee: {health ? health.integrations.cognee.configured ? `${health.integrations.cognee.mode || 'configured'}` : 'not configured' : 'unknown'}</span>{(agent.ingestion || agent.evidence) && <span><Bot size={13} />{agentUsesRelay ? 'ClawMax via Cognee' : 'ClawMax'}: configured</span>}<button aria-label="Refresh backend" disabled={!!busy} onClick={() => void act('refreshing', async () => { await refresh(); setPollStopped(false); setExchanges(previous => previous.map(exchange => exchange.agentStatus === 'waiting' ? { ...exchange, agentStatus: 'pending' } : exchange)); setNotice('Records refreshed.'); })}><RefreshCw className={busy === 'refreshing' ? 'backend-spinning' : ''} size={13} />Refresh</button></div>
      <nav className="backend-tabs" aria-label="Memory workspace">{tabs.map(item => <button key={item.id} aria-current={tab === item.id ? 'page' : undefined} className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)}><item.icon size={15} />{item.name}{item.id === 'records' && records.length > 0 && <span>{records.length}</span>}</button>)}</nav>
      {error && <div className="backend-alert" role="alert"><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError('')}><X size={14} /></button></div>}
      {notice && <div className="backend-notice" role="status"><Check size={14} />{notice}</div>}
      {health && (tab === 'ask' || tab === 'timeline') && <div className="backend-scope"><span><Focus size={14} />{scopedConcept ? `Evidence scope: ${scopedConcept.name}` : 'All reviewed records'}</span>{selectedConcept && <button disabled={!!busy} onClick={() => setExcludedScopeId(scopedConcept ? selectedConcept.id : null)}>{scopedConcept ? 'Use all records' : `Use ${selectedConcept.name}`}</button>}</div>}
      <div className="backend-content">
        {!health ? <div className="backend-empty"><span className="backend-empty-icon">{busy === 'connecting' ? <LoaderCircle className="backend-spinning" size={30} /> : <Database size={30} />}</span><h3>{busy === 'connecting' ? 'Connecting your memory workspace' : 'Start your memory backend'}</h3><p>Your records, reviewed findings, and activity live here.</p>{busy !== 'connecting' && <><code>npm run backend</code><button className="primary-button" disabled={!!busy} onClick={() => void act('connecting', async () => { await refresh(); })}><RefreshCw size={14} />Reconnect</button></>}</div> : <>
          {tab === 'records' && <div className="backend-record-layout">
            <aside className="backend-record-sidebar"><div className="backend-section-heading"><span>YOUR RECORDS</span><button title="Add a record" aria-label="Add a record" disabled={!!busy} onClick={startImport}><Plus size={16} /></button></div>
              {records.length === 0 && <p className="backend-sidebar-empty">Bring in a report to connect your history to your body.</p>}
              <div className="backend-record-list">{records.map(record => <button className={selectedId === record.id && !adding ? 'selected' : ''} key={record.id} onClick={() => openRecord(record)}><FileText size={16} /><span><strong>{record.title}</strong><small>{formatDate(record.event_date)}</small><em className={record.status}>v{record.revision_number ?? 1} · {statusLabels[record.status]}</em></span><ChevronRight size={13} /></button>)}</div>
              {agent.ingestion && <AgentConsent checked={allowDemoAgent} onChange={setAllowDemoAgent} disabled={!!busy}>{`Allow ClawMax${agentRoute} to extract findings from these fictional records.`}</AgentConsent>}
              <button className="backend-demo-button" disabled={!!busy} onClick={() => void act('demo', async () => { const demo = await backend.demo(allowDemoAgent && agent.ingestion); setAllowDemoAgent(false); setPollStopped(false); await refresh(); if (alive.current && demo.records[0]) { openRecord(demo.records[0]); setNotice('Synthetic demo records loaded. These describe a fictional person.'); } })}>{busy === 'demo' ? <LoaderCircle size={14} className="backend-spinning" /> : <Bot size={14} />}Load synthetic demo</button>
              <p className="backend-sidebar-footnote">Three fictional records for exploring memory. Review each before asking questions.</p>
            </aside>
            <section className="backend-record-detail">
              {adding ? <form className="backend-import" onSubmit={event => void submitRecord(event)}><button type="button" className="backend-back" disabled={!!busy} onClick={() => { setAdding(false); setCorrectionId(null); }}><ArrowLeft size={14} />Back to records</button><span className="eyebrow">{correctionId ? 'CORRECTION DRAFT' : 'ADD CONTEXT'}</span><h3>{correctionId ? 'Correct your record.' : 'A record worth remembering.'}</h3><p>{correctionId ? `Create version ${(correction?.revision_number ?? 1) + 1} of “${correction?.title ?? title}”. The approved version and its original source stay available while you review this draft.` : 'Import a report, then review its source and suggested anatomical links.'}</p>{!correctionId && <div className="backend-input-tabs"><button type="button" className={inputMode === 'file' ? 'active' : ''} onClick={() => setInputMode('file')}><Upload size={15} />Upload file</button><button type="button" className={inputMode === 'text' ? 'active' : ''} onClick={() => setInputMode('text')}><FileText size={15} />Paste text</button></div>}
                <label className="backend-field">Record title<input value={title} onChange={event => setTitle(event.target.value)} placeholder="e.g. Left knee MRI report" maxLength={200} required={inputMode === 'text'} /></label>
                <div className="backend-field-row"><label className="backend-field">Record type<select value={recordType} onChange={event => setRecordType(event.target.value)}><option value="medical_report">Medical report</option><option value="clinical_note">Clinical note</option><option value="personal_note">Personal note</option><option value="activity">Activity</option><option value="other">Other</option></select></label><label className="backend-field">Event date <span>(optional)</span><input type="date" name="event_date" value={eventDate} onInput={event => setEventDate(event.currentTarget.value)} onChange={event => setEventDate(event.target.value)} /></label></div>
                {inputMode === 'file' ? <label className="backend-upload"><Upload size={27} /><strong>{file?.name || 'Choose a report'}</strong><span>Text-based PDF, TXT, or Markdown</span><input type="file" accept=".pdf,.txt,.md,text/plain,application/pdf,text/markdown" onChange={event => setFile(event.target.files?.[0] ?? null)} required={!file} /></label> : <label className="backend-field">{correctionId ? 'Corrected transcription' : 'Original report text'}<textarea value={recordText} onChange={event => setRecordText(event.target.value)} placeholder="Paste the report as written, including its date when available…" minLength={1} maxLength={150000} rows={9} required /></label>}
                {agent.ingestion && !correctionId && <AgentConsent checked={allowImportAgent} onChange={setAllowImportAgent} disabled={!!busy}>{`Send this record’s text to ClawMax${agentRoute} for finding extraction.`}</AgentConsent>}
                <div className="backend-review-hint"><ShieldCheck size={16} /><span>{correctionId ? 'The text is prefilled exactly and saved as a new transcription. The original source stays in version history. Review and remap the new findings before approval.' : 'Review happens before memory. You choose which extracted findings are saved.'}</span></div><button className="primary-button" disabled={!!busy || (inputMode === 'file' ? !file : !title.trim() || recordText.trim().length < 1)}>{busy === 'importing' ? <LoaderCircle size={15} className="backend-spinning" /> : <ArrowRight size={15} />}{busy === 'importing' ? correctionId ? 'Creating draft…' : 'Importing record…' : correctionId ? 'Create correction draft' : 'Import and review'}</button>
              </form> : selected ? <>
                <div className="backend-record-heading"><span className="eyebrow">{readable(selected.record_type).toUpperCase()}</span><h3>{selected.title}</h3><div><span><Clock3 size={12} />{formatDate(selected.event_date)}</span><span className={`backend-version-badge ${selected.status}`}>Version {selected.revision_number ?? 1} · {statusLabels[selected.status]}</span>{(selected.status === 'approved' || selected.status === 'pending_review') && <span className={`backend-memory-status ${selected.memory_status}`}>{selected.memory_status === 'pending' && <LoaderCircle size={11} className="backend-spinning" />}{memoryLabels[selected.memory_status]}</span>}</div></div>
                <div className="backend-record-actions">
                  {selected.status === 'approved' && (pendingCorrection ? <button className="secondary-button" disabled={!!busy} onClick={() => openRecord(pendingCorrection)}><Pencil size={13} />Review correction draft</button> : <button className="secondary-button" disabled={!!busy} onClick={() => startCorrection(selected)}><Pencil size={13} />Create correction</button>)}
                  {selected.status !== 'deleting' && <button className="backend-delete-button" disabled={!!busy} onClick={() => setDeleteConfirmId(selected.id)}><Trash2 size={13} />Delete record</button>}
                </div>
                {(deleteConfirmId === selected.id || selected.status === 'deleting') && <section className="backend-delete-confirm" aria-labelledby="delete-record-heading">
                  <h4 id="delete-record-heading">{selected.status === 'deleting' ? 'Deletion needs to finish' : 'Delete this record?'}</h4>
                  <p><strong>“{selected.title}” · version {selected.revision_number ?? 1}</strong><br />{formatDate(selected.event_date)}</p>
                  <p>{selected.status === 'deleting' ? 'This record is excluded from answers while cleanup is pending. Retry to remove its source, findings, and connected Cognee memory.' : 'This permanently removes this version’s source, findings, and connected Cognee memory. Conversations citing it will be cleared from this browser. Other versions stay in history; deleting this version does not restore a previous version to memory.'}</p>
                  {selected.deletion_error && <p className="backend-deletion-error" role="alert">{selected.deletion_error}</p>}
                  <div>{selected.status !== 'deleting' && <button className="secondary-button" disabled={!!busy} onClick={() => setDeleteConfirmId(null)}>Keep record</button>}<button className="backend-danger-button" disabled={!!busy} onClick={() => void deleteRecord(selected)}>{busy === 'deleting' ? <LoaderCircle size={14} className="backend-spinning" /> : <Trash2 size={14} />}{busy === 'deleting' ? 'Removing record…' : selected.status === 'deleting' ? 'Retry deletion' : 'Permanently delete record'}</button></div>
                </section>}
                {(versions.length > 1 || selected.revises_record_id || selected.superseded_by) && <section className="backend-version-history" aria-label="Version history"><h4><History size={14} />Version history</h4>
                  {selected.status === 'superseded' && <p>This version is retained as history and excluded from answers.</p>}
                  {selected.status === 'pending_review' && selected.revises_record_id && <p>Correction draft. Approving it replaces the previous approved version in memory.</p>}
                  {selected.revises_record_id && !records.some(record => record.id === selected.revises_record_id) && <p>The earlier source version is no longer available.</p>}
                  {selected.superseded_by && !records.some(record => record.id === selected.superseded_by) && <p>The replacement version is no longer available. This version remains excluded from memory.</p>}
                  <div>{versions.map(version => <button key={version.id} className={version.id === selected.id ? 'current' : ''} aria-current={version.id === selected.id ? 'true' : undefined} disabled={version.id === selected.id} onClick={() => openRecord(version)}><span>v{version.revision_number ?? 1} · {statusLabels[version.status]}</span><strong>{version.title}</strong>{version.id !== selected.id && <ArrowRight size={12} />}</button>)}</div>
                </section>}
                {selected.status !== 'deleting' && <>
                <Notices messages={selected.warnings} />
                <div className="backend-review-tabs"><button className={reviewTab === 'findings' ? 'active' : ''} onClick={() => setReviewTab('findings')}>Review findings <span>{selected.findings.length}</span></button><button className={reviewTab === 'source' ? 'active' : ''} onClick={() => setReviewTab('source')}>{selected.source_kind === 'corrected_transcription' || selected.revises_record_id ? 'Corrected transcription' : 'Original text'}</button><a href={backend.sourceUrl(selected.id)} target="_blank" rel="noreferrer">{selected.source_kind === 'corrected_transcription' || selected.revises_record_id ? 'Open transcription' : 'Open original'} <ArrowRight size={12} /></a></div>
                {reviewTab === 'source' ? <div className="backend-source">{selected.pages.length ? selected.pages.map(page => <section key={page.page}><span>PAGE {page.page}</span><pre>{page.text}</pre></section>) : <pre>{selected.text}</pre>}</div> : <>
                  <div className="backend-review-explainer"><ShieldCheck size={18} /><p>{selected.status === 'approved' ? 'This record has been reviewed. Answers use approved source evidence.' : selected.status === 'superseded' ? 'Historical findings are preserved for comparison. This superseded version is excluded from answers and the timeline.' : 'Check the quoted passages and proposed anatomical links. Select the findings you want to keep in memory.'}</p></div>
                  {selected.findings.length === 0 && <div className="backend-inline-empty"><FileText size={22} /><p>No findings were extracted. The source is preserved; memory approval needs at least one source passage.</p></div>}
                  <div className="backend-findings">{selected.findings.map(finding => <article key={finding.id} className={selected.status !== 'pending_review' && finding.approved === false ? 'excluded' : selected.status === 'pending_review' && findingIds.includes(finding.id) ? 'included' : ''}><div className="backend-finding-heading">{selected.status === 'pending_review' ? <label><input type="checkbox" checked={findingIds.includes(finding.id)} onChange={event => setFindingIds(previous => event.target.checked ? [...previous, finding.id] : previous.filter(id => id !== finding.id))} /><span>{finding.anatomy_query || 'Source finding'}</span></label> : <span>{finding.approved === false ? <X size={14} /> : <CheckCheck size={14} />}{finding.anatomy_query || 'Source finding'}{finding.approved === false && <em>Excluded from memory</em>}</span>}<small>Page {finding.page}</small></div><blockquote>{finding.quote}</blockquote><div className="backend-mapping">{finding.concept ? <button onClick={() => selectConcept(finding.concept!)}><Focus size={13} />{finding.concept.name}<ArrowRight size={12} /></button> : <span>No matching structure in the atlas</span>}{finding.laterality && <small>{finding.laterality}</small>}{selected.status === 'pending_review' && <button className="backend-edit-mapping" onClick={() => { setMappingFindingId(mappingFindingId === finding.id ? null : finding.id); setMappingQuery(finding.concept?.name || finding.anatomy_query); }}>Change link</button>}</div>{mappingFindingId === finding.id && <div className="backend-mapping-editor"><label htmlFor={`mapping-${finding.id}`}>Search the anatomy atlas</label><input id={`mapping-${finding.id}`} autoFocus value={mappingQuery} onChange={event => setMappingQuery(event.target.value)} placeholder="e.g. right femur" maxLength={200} /><div>{mappingSearching ? <p>Searching anatomy…</p> : mappingResults.length ? mappingResults.map(concept => <button key={concept.id} disabled={!!busy} onClick={() => void updateMapping(finding.id, concept.id)}><span>{concept.name}<small>{concept.id} · {concept.elements.length} modeled pieces</small></span><Check size={13} /></button>) : <p>No matching structures. Try another name.</p>}</div><button disabled={!!busy} className="backend-unlink" onClick={() => void updateMapping(finding.id, null)}>Keep passage without an anatomical link</button></div>}</article>)}</div>
                  {selected.status === 'pending_review' ? <div className="backend-approve"><p>{selected.findings.length ? `${findingIds.length} of ${selected.findings.length} findings selected` : 'The original record will be preserved.'}</p><button className="primary-button" disabled={!!busy || findingIds.length === 0} onClick={() => void approveRecord(selected)}>{busy === 'approving' ? <LoaderCircle size={15} className="backend-spinning" /> : <ShieldCheck size={15} />}{selected.revises_record_id ? 'Approve correction and replace in memory' : 'Approve and save to memory'}</button></div> : selected.status === 'approved' ? <div className="backend-approved"><span><CheckCheck size={17} />Review complete</span>{(selected.memory_status === 'failed' || selected.memory_status === 'unconfigured' || selected.memory_status === 'not_indexed' || selected.memory_status === 'retired') && <button className="secondary-button" disabled={!!busy || !health.integrations.cognee.configured} onClick={() => void act('indexing', async () => { await backend.index(selected.id); await refresh(); if (alive.current) setPollStopped(false); })}><RefreshCw size={13} />Retry Cognee indexing</button>}<button className="secondary-button" onClick={() => setTab('ask')}><MessageCircle size={14} />Ask your records</button></div> : null}
                </>}
                </>}
              </> : <div className="backend-empty"><span className="backend-empty-icon"><FileText size={30} /></span><span className="eyebrow">EVIDENCE, CONNECTED</span><h3>Your history has a place here.</h3><p>Connect reports to anatomy, review what is remembered, and ask questions with the original sources close by.</p><button className="primary-button" onClick={startImport}><Plus size={15} />{records.length ? 'Add a record' : 'Add your first record'}</button><small>Your existing atlas notes stay in this browser.</small></div>}
            </section>
          </div>}
          {tab === 'ask' && <section className="backend-ask"><div className="backend-page-heading"><span className="eyebrow">A CONVERSATION WITH YOUR HISTORY</span><h3>What would you like to remember?</h3><p>Answers refer to reviewed records and include the passages they use.</p></div>
            <div className="backend-history-controls"><p>{historySaved ? 'Recent conversation saved in this browser.' : 'Browser storage is unavailable. This conversation lasts for this session.'}</p><button disabled={!!busy || exchanges.length === 0} onClick={clearHistory}><Trash2 size={13} />Clear history</button></div>
            {exchanges.length === 0 && <div className="backend-prompts"><span><Bot size={23} /></span><p>{health.counts.approved ? `${health.counts.approved} reviewed ${health.counts.approved === 1 ? 'record is' : 'records are'} ready to explore.` : 'Review and approve a record to start building memory.'}</p><div>{['What do my records say about my lumbar spine?', 'Which nerve did my report mention?', 'How has my history changed over time?'].map(prompt => <button key={prompt} disabled={!!busy} onClick={() => setQuestion(prompt)}>{prompt}<ArrowRight size={13} /></button>)}</div></div>}
            <div className="backend-exchanges">{exchanges.map((exchange, index) => <article key={index}><div className="backend-question"><span>You · {exchange.scopeName ? `Scoped to ${exchange.scopeName}` : 'All reviewed records'}</span><p>{exchange.question}</p></div><div className="backend-answer"><span><Bot size={16} />BodyBrain <em>{exchange.agentStatus === 'completed' ? 'ClawMax citation selection · verified quotes' : exchange.response.retrieval_mode === 'cognee' ? 'Cognee retrieval' : 'Local evidence retrieval'}</em></span><p>{exchange.response.answer}</p>{exchange.agentStatus === 'pending' && <div className="backend-thinking"><LoaderCircle size={13} className="backend-spinning" />Waiting for ClawMax to return verified citations. Current retrieved evidence remains available.</div>}{exchange.agentStatus === 'waiting' && <Notices messages={['The ClawMax result is still pending or could not be checked. Use Refresh to check again.']} />}{exchange.agentStatus === 'failed' && <Notices messages={['The ClawMax workflow could not complete. The retrieved evidence remains available.']} />}<Notices messages={exchange.response.warnings} /><SourceCitations citations={exchange.response.citations} onOpen={openCitation} />{exchange.response.concepts.length > 0 && <div className="backend-answer-anatomy">{exchange.response.concepts.map(concept => <button key={concept.id} onClick={() => selectConcept(concept)}><Focus size={13} />{concept.name}<ArrowRight size={12} /></button>)}</div>}</div></article>)}</div>
            {busy === 'asking' && <div className="backend-thinking" role="status"><LoaderCircle size={15} className="backend-spinning" />Reading your approved evidence…</div>}
            {agent.evidence && <AgentConsent checked={allowChatAgent} onChange={setAllowChatAgent} disabled={!!busy}>{`Send this question and approved source passages to ClawMax${agentRoute} to select citations.`}</AgentConsent>}
            <form className="backend-chat-form" onSubmit={event => void ask(event)}><label className="sr-only" htmlFor="backend-question">Ask a question about your records</label><textarea id="backend-question" value={question} onChange={event => setQuestion(event.target.value)} placeholder="Ask about a finding, a body part, or your history…" rows={2} maxLength={2000} required onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); if (!busy && question.trim()) void ask(event); } }} /><button className="primary-button" aria-label="Send question" type="submit" disabled={!!busy || !question.trim()}><Send size={17} /></button></form><p className="backend-chat-footnote">Grounded in your records. This workspace does not diagnose symptoms.</p>
          </section>}
          {tab === 'timeline' && <section className="backend-timeline"><div className="backend-page-heading"><span className="eyebrow">YOUR BODY OVER TIME</span><h3>A connected history.</h3><p>Reviewed records in time, with a path back to every source.</p></div>{events.length ? <div className="backend-timeline-list">{events.map(record => <article key={record.id}><time>{formatDate(record.event_date)}</time><div><span>{readable(record.record_type)}</span><button onClick={() => openRecord(record)}><h4>{record.title}</h4><ArrowRight size={15} /></button>{record.findings.filter((finding, index, all) => finding.approved !== false && all.findIndex(other => other.approved !== false && other.page === finding.page && other.quote === finding.quote) === index).slice(0, 2).map(finding => <p key={finding.id}>{finding.quote}</p>)}<small>{record.findings.filter(finding => finding.approved !== false).length} approved findings · {memoryLabels[record.memory_status]}</small></div></article>)}</div> : <div className="backend-inline-empty"><Clock3 size={27} /><p>{scopedConcept ? `No approved records are linked to ${scopedConcept.name}.` : 'Approved records will build your timeline.'}</p><button className="secondary-button" onClick={() => setTab('records')}>Review records<ArrowRight size={14} /></button></div>}</section>}
          {tab === 'activity' && <section className="backend-activity"><div className="backend-page-heading"><span className="eyebrow">VISIBLE WORKFLOWS</span><h3>Behind each memory.</h3><p>Inspect ingestion, review, retrieval, and memory runs.</p></div>{runs.length ? <div className="backend-runs">{runs.map(run => <details key={run.id}><summary><span className={`backend-run-indicator ${run.status}`} /><span><strong>{readable(run.kind)}</strong><small>{formatDate(run.created_at)} · {readable(run.status)}</small></span><ChevronRight size={15} /></summary><div className="backend-run-steps">{run.steps.map((step, index) => <div key={`${index}:${step.name}`}><span className={`backend-run-indicator ${step.status}`} /><div><strong>{readable(step.name)}<small>{readable(step.status)}</small></strong>{step.detail && <p>{step.detail}</p>}</div></div>)}<small className="backend-run-id">Run {run.id}</small></div></details>)}</div> : <div className="backend-inline-empty"><Activity size={27} /><p>Import or query a record to see its workflow here.</p></div>}</section>}
        </>}
      </div>
      <footer className="backend-footer"><ShieldCheck size={12} /><span>Source first. Human reviewed. Connected to your anatomy.</span><button onClick={onClose}>Back to atlas<ArrowRight size={12} /></button></footer>
    </div>
  </dialog>;
}
