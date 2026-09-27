import { lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  Activity, ArrowDownToLine, ArrowLeft, ArrowRight, Bookmark, Box, Brain,
  Check, ChevronRight, CircleHelp, Clock3, Expand, Eye, EyeOff, Focus,
  Heart, Layers3, Leaf, Menu, Minus, Moon, MousePointer2, Plus, Sun,
  RotateCcw, RotateCw, Search, ShieldCheck, Sparkles, StickyNote, X,
} from 'lucide-react';
import AnatomyScene from './anatomy/scene';
import { SYSTEMS, EXPLANATIONS, explanation, type Atlas, type Concept, type SceneState, type SystemId, type View } from './anatomy/anatomy';
import { REGIONS, FEATURED, getRegionConcepts } from './body-regions';
const BackendPanel = lazy(() => import('./BackendPanel'));

const BASE_SYSTEMS: SystemId[] = ['skeletal', 'cardiac', 'sensory', 'nervous', 'respiratory', 'digestive', 'urinary', 'endocrine', 'reproductive'];
const initialState: SceneState = { explode: 0, visible: BASE_SYSTEMS, selected: [], isolate: false, view: 'front', rotate: false, reset: 0, labels: true, zoom: 1, opacity: 1, hidden: [] };
type Memory = { id: string; concept: Concept; text: string; createdAt: string };
type Panel = 'overview' | 'memories' | 'timeline';

function readSaved<T,>(key: string, fallback: T): T {
  try { const value = localStorage.getItem(key); return value ? JSON.parse(value) as T : fallback; } catch { return fallback; }
}
function BodyGlyph({ region, className = '' }: { region?: string; className?: string }) {
  region = region?.split('-')[0];
  return <svg className={`body-glyph ${className}`} viewBox="0 0 56 96" fill="none" aria-hidden="true">
    <g stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="28" cy="10" r="6" fill={region === 'head' ? 'currentColor' : 'none'} />
      <path d="M25 16v5l-8 3-4 18-6 15 4 2 8-15 2-13v21l-2 19-2 20h6l5-35 5 35h6l-2-20-2-19V31l2 13 8 15 4-2-6-15-4-18-8-3v-5" />
      <path d="M21 27h14v14H21z" fill={region === 'chest' ? 'currentColor' : 'none'} opacity=".65" />
      <path d="M21 43h14v12H21z" fill={region === 'abdomen' ? 'currentColor' : 'none'} opacity=".65" />
      <path d="M18 26l-4 18-6 13m30-31 4 18 6 13" strokeWidth={region === 'arms' ? 5 : 1.5} opacity=".7" />
      <path d="M23 58l-3 30m13-30 3 30" strokeWidth={region === 'legs' ? 5 : 1.5} opacity=".7" />
      <path d="M28 22v30m-7-20h14m-14 4h14m-14 12h14" opacity=".35" />
    </g>
  </svg>;
}
function IconButton({ label, children, onClick, active, disabled = false }: { label: string; children: ReactNode; onClick: () => void; active?: boolean; disabled?: boolean }) {
  return <button className={`icon-button ${active ? 'active' : ''}`} title={label} aria-label={label} aria-pressed={active} disabled={disabled} onClick={onClick}>{children}</button>;
}
function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog className="modal" aria-label={title} ref={dialog} onCancel={onClose} onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="modal-heading"><h2>{title}</h2><IconButton label="Close dialog" onClick={onClose}><X size={20} /></IconButton></div>
    {children}
  </dialog>;
}

export default function App() {
  const [theme, setTheme] = useState<'light' | 'dark'>(() => document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');
  const [atlas, setAtlas] = useState<Atlas | null>(null);
  const [state, setState] = useState<SceneState>(initialState);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState('');
  const [browse, setBrowse] = useState<'regions' | 'systems' | 'layers'>('regions');
  const [region, setRegion] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [chosen, setChosen] = useState<Concept | null>(null);
  const [panel, setPanel] = useState<Panel>('overview');
  const [mobilePanel, setMobilePanel] = useState<'browse' | 'details' | null>(null);
  const [modal, setModal] = useState<'credits' | 'help' | 'note' | null>(null);
  const [backendOpen, setBackendOpen] = useState(false);
  const [backendLoaded, setBackendLoaded] = useState(false);
  const [note, setNote] = useState('');
  const [memories, setMemories] = useState<Memory[]>(() => readSaved('bodybrain.memories.v1', []));
  const [bookmarks, setBookmarks] = useState<Concept[]>(() => readSaved('bodybrain.bookmarks.v1', []));
  const [toast, setToast] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'light' ? '#f7f8fa' : '#121419');
  }, [theme]);
  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    try { localStorage.setItem('bodybrain.theme', next); } catch { /* Theme still works when storage is unavailable. */ }
  };

  useEffect(() => {
    const controller = new AbortController();
    fetch('/models/atlas.json', { signal: controller.signal }).then(r => { if (!r.ok) throw new Error('Could not load the anatomy catalogue.'); return r.json(); }).then(setAtlas).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => controller.abort();
  }, []);
  useEffect(() => { if (!toast) return; const timeout = setTimeout(() => setToast(''), 3500); return () => clearTimeout(timeout); }, [toast]);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.key === '/' || ((e.metaKey || e.ctrlKey) && e.key === 'k')) && !(e.target instanceof HTMLInputElement) && !(e.target instanceof HTMLTextAreaElement)) { e.preventDefault(); setMobilePanel('browse'); searchRef.current?.focus(); }
      if (e.key === 'Escape' && !modal) { setBackendOpen(false); setQuery(''); setMobilePanel(null); }
    };
    window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler);
  }, [modal]);

  const parts = useMemo(() => new Map(atlas?.parts.map(p => [p.id, p])), [atlas]);
  const counts = useMemo(() => Object.fromEntries(SYSTEMS.map(s => [s.id, atlas?.parts.filter(p => p.system === s.id).length ?? 0])), [atlas]);
  const selectedPart = chosen ? parts.get(chosen.elements[0]) : undefined;
  const system = SYSTEMS.find(s => s.id === selectedPart?.system);
  const visibleCount = atlas?.parts.filter(p => !state.hidden?.includes(p.id) && (state.isolate ? state.selected.includes(p.id) : state.visible.includes(p.system) || state.selected.includes(p.id))).length ?? 0;
  const spreadPartCount = state.selected.length ? state.selected.filter(id => parts.has(id) && !state.hidden?.includes(id)).length : visibleCount;
  const results = useMemo(() => {
    if (!atlas || !query.trim()) return [];
    const term = query.trim().toLowerCase();
    return atlas.concepts.filter(c => c.name.toLowerCase().includes(term) || c.id.toLowerCase().includes(term))
      .sort((a, b) => Number(b.name.toLowerCase() === term) - Number(a.name.toLowerCase() === term) || a.name.length - b.name.length).slice(0, 60);
  }, [atlas, query]);
  const relevantMemories = chosen ? memories.filter(m => m.concept.elements.some(id => chosen.elements.includes(id))) : memories;
  const sameSelection = (a: Concept, b: Concept) => a.id === b.id && a.elements.length === b.elements.length && a.elements.every(id => b.elements.includes(id));
  const selectedBookmark = !!chosen && bookmarks.some(c => sameSelection(c, chosen));

  const choose = (concept: Concept, isolate = false) => {
    setChosen(concept); setPanel('overview'); setQuery(''); setMobilePanel('details');
    setState(s => ({ ...s, selected: concept.elements, isolate, explode: 0, rotate: false, zoom: 1, hidden: s.hidden?.filter(id => !concept.elements.includes(id)) }));
  };
  const chooseName = (name: string, isolate = true) => { const concept = atlas?.concepts.find(c => c.name.toLowerCase() === name.toLowerCase()); if (concept) choose(concept, isolate); };
  const choosePart = (id: string) => { const part = parts.get(id); if (part) choose({ id: part.conceptId, name: part.name, elements: [id] }, state.isolate); };
  const reset = () => { setState(s => ({ ...initialState, reset: s.reset + 1 })); setChosen(null); setRegion(null); setQuery(''); setPanel('overview'); setMobilePanel(null); };
  const clearSelection = () => { setChosen(null); setState(s => ({ ...s, selected: [], isolate: false, explode: 0, zoom: 1 })); };
  const preset = (visible: SystemId[]) => { clearSelection(); setState(s => ({ ...s, visible, hidden: [], explode: 0, reset: s.reset + 1 })); };
  const toggleSystem = (id: SystemId) => { clearSelection(); setState(s => ({ ...s, visible: s.visible.includes(id) ? s.visible.filter(x => x !== id) : [...s.visible, id] })); };
  const saveNote = () => {
    if (!chosen || !note.trim()) return;
    const next = [{ id: crypto.randomUUID(), concept: chosen, text: note.trim(), createdAt: new Date().toISOString() }, ...memories];
    try { localStorage.setItem('bodybrain.memories.v1', JSON.stringify(next)); setMemories(next); setNote(''); setModal(null); setPanel('memories'); setToast('Memory saved on this device'); } catch { setToast('Browser storage is full. Your note has not been saved.'); }
  };
  const toggleBookmark = () => {
    if (!chosen) return;
    const next = selectedBookmark ? bookmarks.filter(c => !sameSelection(c, chosen)) : [...bookmarks, chosen];
    try { localStorage.setItem('bodybrain.bookmarks.v1', JSON.stringify(next)); setBookmarks(next); setToast(selectedBookmark ? 'Structure removed from saved' : 'Structure saved'); } catch { setToast('Could not save to browser storage'); }
  };
  const exportMemories = () => {
    const blob = new Blob([JSON.stringify(memories, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'bodybrain-memories.json'; a.click(); URL.revokeObjectURL(url);
  };
  const removeMemory = (id: string) => {
    const next = memories.filter(memory => memory.id !== id);
    try { localStorage.setItem('bodybrain.memories.v1', JSON.stringify(next)); setMemories(next); setToast('Memory removed'); } catch { setToast('Could not update browser storage'); }
  };
  const viewNames: [View, string][] = [['front', 'Front'], ['back', 'Back'], ['side', 'Side'], ['three-quarter', 'Perspective']];

  return <main className="app-shell">
    <header className="app-header">
      <a className="brand" href="#" onClick={e => { e.preventDefault(); reset(); }} aria-label="BodyBrain home"><span className="brand-symbol"><Activity size={24} strokeWidth={1.6} /></span><span>body<span className="brand-light">brain</span><span className="brand-dot">.</span></span></a>
      <div className="header-divider" />
      <span className="workspace-name">Your body, connected</span>
      <nav className="main-nav" aria-label="Main navigation">
        <button aria-label="Body atlas" title="Body atlas" className={panel === 'overview' ? 'selected' : ''} onClick={() => { setPanel('overview'); setMobilePanel(null); }}><Box size={15} />Body atlas</button>
        <button aria-label="My memories" title="My memories" className={panel === 'memories' ? 'selected' : ''} onClick={() => { clearSelection(); setPanel('memories'); setMobilePanel('details'); }}><Bookmark size={15} />My memories<span className="nav-count">{memories.length}</span></button>
        <button aria-label="Timeline" title="Timeline" className={panel === 'timeline' ? 'selected' : ''} onClick={() => { clearSelection(); setPanel('timeline'); setMobilePanel('details'); }}><Clock3 size={15} />Timeline</button>
        <button aria-label="Records and memory" title="Records & memory" className={backendOpen ? 'selected' : ''} onClick={() => { setBackendLoaded(true); setBackendOpen(true); }}><Brain size={15} />Records & memory</button>
      </nav>
      <div className="header-end"><span className="prototype-badge"><span />Personal atlas</span><button className="icon-button theme-toggle" aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`} title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`} onClick={toggleTheme}>{theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}</button><IconButton label="Help and shortcuts" onClick={() => setModal('help')}><CircleHelp size={18} /></IconButton><div className="avatar" title="Local workspace">You</div></div>
    </header>

    <div className="workspace">
      <aside className={`browse-panel ${mobilePanel === 'browse' ? 'mobile-open' : ''}`} aria-label="Browse anatomy">
        <div className="sidebar-heading"><div><span className="eyebrow">THE HUMAN BODY</span><h1>Explore your anatomy</h1></div><button className="mobile-only icon-button" aria-label="Close browse" onClick={() => setMobilePanel(null)}><X size={18} /></button></div>
        <label className="search-box"><Search size={16} /><input ref={searchRef} value={query} onChange={e => setQuery(e.target.value)} placeholder="Find a structure…" aria-label="Find a structure" /><kbd>/</kbd></label>
        {query.trim() ? <div className="search-content"><div className="section-label">{results.length} {results.length === 1 ? 'MATCH' : 'MATCHES'}{results.length === 60 ? ' · REFINE TO SEE MORE' : ''}</div><div className="search-results">{results.map(c => <button key={c.id} onClick={() => choose(c, true)}><span>{c.name}<small>{c.elements.length} {c.elements.length === 1 ? 'structure' : 'structures'}</small></span><ChevronRight size={14} /></button>)}{!results.length && <div className="empty-small"><Search size={24} /><p>No structures found.</p><span>Try “heart”, “femur”, or “lumbar”.</span></div>}</div></div> : <>
          <div className="browse-tabs" role="tablist" aria-label="Browse by">{(['regions', 'systems', 'layers'] as const).map(tab => <button key={tab} role="tab" aria-selected={browse === tab} onClick={() => { setBrowse(tab); setRegion(null); }}>{tab[0].toUpperCase() + tab.slice(1)}</button>)}</div>
          <div className="browse-content">
            {browse === 'regions' && !region && <><p className="sidebar-description">Start with a region.<br />Discover what makes you, you.</p><div className="region-list">{REGIONS.map(r => <button className="region-row" key={r.id} onClick={() => setRegion(r.id)}><span className={`region-art region-${r.id}`}><BodyGlyph region={r.id} /></span><span><strong>{r.name}</strong><small>{r.subtitle}</small></span><ArrowRight size={16} /></button>)}</div>{bookmarks.length > 0 && <div className="saved-structures"><span className="section-label">SAVED STRUCTURES</span>{bookmarks.map(c => <button key={`${c.id}:${c.elements.join(',')}`} onClick={() => choose(c, true)}><Bookmark size={13} /><span>{c.name}</span><ChevronRight size={13} /></button>)}</div>}</>}
            {browse === 'regions' && region && <><button className="back-link" onClick={() => setRegion(null)}><ArrowLeft size={14} />All regions</button><h2 className="region-title">{REGIONS.find(r => r.id === region)?.name}</h2><p className="sidebar-description">Select a structure for a closer look.</p><div className="structure-list">{atlas && getRegionConcepts(atlas, region).map(c => <button key={c.id} onClick={() => choose(c, true)}><span>{c.name}</span><ChevronRight size={14} /></button>)}</div></>}
            {browse === 'systems' && <><p className="sidebar-description">Reveal the systems that work together.</p><div className="preset-row"><button onClick={() => preset(SYSTEMS.map(s => s.id))}>All</button><button onClick={() => preset(['skeletal'])}>Skeleton</button><button onClick={() => preset(['cardiac', 'respiratory', 'digestive', 'urinary', 'endocrine', 'reproductive'])}>Organs</button></div><div className="systems-list">{SYSTEMS.map(s => <div className="system-row" key={s.id}><button className="system-name" title={`Show only ${s.name}`} onClick={() => preset([s.id])}><span className="system-dot" style={{ background: s.color }} /><span>{s.name}</span><small>{counts[s.id]}</small></button><button className={`switch ${state.visible.includes(s.id) ? 'on' : ''}`} role="switch" aria-checked={state.visible.includes(s.id)} aria-label={`Show ${s.name.toLowerCase()}`} onClick={() => toggleSystem(s.id)}><span /></button></div>)}</div><button className="text-button" onClick={() => preset([])}>Hide all systems</button></>}
            {browse === 'layers' && <><p className="sidebar-description">See your body from a different layer.</p>{[{ name: 'Essential anatomy', description: 'Skeleton and internal organs', ids: BASE_SYSTEMS }, { name: 'Musculoskeletal', description: 'Bones, muscles, and connective tissue', ids: ['skeletal', 'muscular', 'connective'] as SystemId[] }, { name: 'Internal organs', description: 'The systems beneath the surface', ids: ['cardiac', 'respiratory', 'digestive', 'urinary', 'endocrine', 'reproductive'] as SystemId[] }, { name: 'Nervous system', description: 'Brain, spinal cord, and modeled nerves', ids: ['nervous'] as SystemId[] }, { name: 'Circulation', description: 'Heart, arteries, and veins', ids: ['cardiac', 'arterial', 'venous'] as SystemId[] }].map(layer => <button className={`layer-card ${layer.ids.length === state.visible.length && layer.ids.every(id => state.visible.includes(id)) ? 'selected' : ''}`} key={layer.name} onClick={() => preset(layer.ids)}><Layers3 size={20} /><span><strong>{layer.name}</strong><small>{layer.description}</small></span><ChevronRight size={14} /></button>)}<div className="opacity-control"><label htmlFor="opacity">Layer opacity<span>{Math.round((state.opacity ?? 1) * 100)}%</span></label><input id="opacity" type="range" min="15" max="100" value={(state.opacity ?? 1) * 100} onChange={e => setState(s => ({ ...s, opacity: Number(e.target.value) / 100 }))} /></div></>}
          </div>
        </>}
        <div className="sidebar-bottom"><button className="label-toggle" aria-pressed={!!state.labels} onClick={() => setState(s => ({ ...s, labels: !s.labels }))}><Eye size={16} /><span>Structure labels</span><span className={`switch ${state.labels ? 'on' : ''}`}><span /></span></button><button className="credits-button" onClick={() => setModal('credits')}><ShieldCheck size={14} />Source & credits<ArrowRight size={12} /></button></div>
      </aside>

      <section className="body-stage" aria-label="Interactive body atlas">
        {atlas && <AnatomyScene atlas={atlas} theme={theme} state={{ ...state, inspectorOpen: false }} onSelect={choosePart} onProgress={setProgress} onError={setError} />}
        <div className="stage-top"><span className="stage-label"><span className="live-dot" />{visibleCount.toLocaleString()} structures visible</span><div className="stage-top-actions"><span className="model-tag">ADULT · MALE</span><IconButton label="Reset view and anatomy" onClick={reset}><RotateCcw size={17} /></IconButton><IconButton label="Toggle fullscreen" onClick={() => { if (document.fullscreenElement) void document.exitFullscreen(); else void document.documentElement.requestFullscreen().catch(() => setToast('Fullscreen is unavailable in this browser')); }}><Expand size={16} /></IconButton></div></div>
        <div className="mobile-stage-tools"><button onClick={() => setMobilePanel('browse')}><Menu size={17} />Browse</button><button onClick={() => setMobilePanel('details')}><StickyNote size={17} />Details</button></div>
        {chosen && <div className="selection-chip"><span /><span>{chosen.name}</span><button aria-label="Clear selection" onClick={clearSelection}><X size={13} /></button></div>}
        <div className="zoom-controls"><IconButton label="Zoom in" onClick={() => setState(s => ({ ...s, zoom: Math.min(2.5, (s.zoom ?? 1) + .2) }))}><Plus size={17} /></IconButton><span /><IconButton label="Zoom out" onClick={() => setState(s => ({ ...s, zoom: Math.max(.55, (s.zoom ?? 1) - .2) }))}><Minus size={17} /></IconButton><span /><IconButton label={state.rotate ? 'Pause rotation' : 'Auto rotate'} active={state.rotate} disabled={state.isolate || state.explode >= .4} onClick={() => setState(s => ({ ...s, rotate: !s.rotate }))}><RotateCw size={16} /></IconButton></div>
        <div className="orientation" aria-label="Anatomical orientation"><span>S</span><div><span>R</span><strong>{state.view === 'back' ? 'P' : state.view === 'side' ? 'L' : 'A'}</strong><span>L</span></div><span>I</span></div>
        <div className="view-dock">
          <div className="view-tabs" role="group" aria-label="View angle">{viewNames.map(([view, label]) => <button key={view} aria-pressed={state.view === view} disabled={state.explode > .8 && view !== 'front'} className={state.view === view ? 'active' : ''} onClick={() => setState(s => ({ ...s, view, rotate: false, reset: s.reset + 1 }))}>{label}</button>)}</div>
          <div className="spread-heading"><label htmlFor="spread"><Box size={14} />Spread structures apart</label><button disabled={state.explode === 0} onClick={() => setState(s => ({ ...s, explode: 0 }))}><RotateCcw size={12} />Reassemble</button><output>{Math.round(state.explode * 100)}%</output></div>
          <p id="spread-scope" className="spread-scope">{chosen ? spreadPartCount === 1 ? `${chosen.name} is one modeled piece; there are no smaller pieces to separate.` : `${chosen.name} only · ${spreadPartCount} pieces` : `All visible anatomy · ${spreadPartCount} pieces`}</p>
          <input id="spread" className="spread-slider" type="range" min="0" max="100" disabled={spreadPartCount < 2} aria-describedby="spread-scope" value={state.explode * 100} style={{ '--range-progress': `${state.explode * 100}%` } as React.CSSProperties} onChange={e => { const value = Number(e.target.value) / 100; setState(s => ({ ...s, explode: value, isolate: s.selected.length > 0, rotate: false, zoom: 1, view: value > .8 ? 'front' : s.view })); }} />
          <div className="range-labels"><span>Assembled</span><span>Every piece</span></div>
        </div>
        <div className="stage-instructions"><MousePointer2 size={12} /><span>Drag to orbit</span><i />Scroll to zoom<i /><span>Click to explore</span></div>
        {progress < 100 && !error && <div className="loading-overlay"><div className="loading-card"><div className="loading-orbit"><Activity size={26} /></div><h2>Getting to know the human body</h2><p>Loading {atlas?.parts.length.toLocaleString() ?? '2,234'} anatomical structures</p><div className="loading-track"><span style={{ width: `${progress}%` }} /></div><span className="loading-percent">{progress}%</span></div></div>}
        {error && <div className="loading-overlay"><div className="loading-card"><CircleHelp size={28} /><h2>The atlas couldn’t load</h2><p>{error}</p><button className="primary-button" onClick={() => location.reload()}>Try again</button></div></div>}
      </section>

      <aside className={`inspector-panel ${mobilePanel === 'details' ? 'mobile-open' : ''}`} aria-label="Structure details">
        <div className="inspector-top"><span className="eyebrow">{panel === 'overview' ? 'YOUR BODY ATLAS' : panel === 'memories' ? 'PERSONAL MEMORY' : 'YOUR BODY OVER TIME'}</span><button className="mobile-only icon-button" aria-label="Close details" onClick={() => setMobilePanel(null)}><X size={18} /></button>{chosen && <IconButton label={selectedBookmark ? 'Unsave structure' : 'Save structure'} onClick={toggleBookmark} active={selectedBookmark}><Bookmark size={17} fill={selectedBookmark ? 'currentColor' : 'none'} /></IconButton>}</div>
        <div className="inspector-scroll">
          {panel === 'overview' && !chosen && <div className="welcome-panel"><span className="welcome-symbol"><Sparkles size={26} strokeWidth={1.3} /></span><h2>A closer look<br />at <span>you.</span></h2><p>Every part has a story.<br />Explore the anatomy that connects it all.</p><div className="welcome-rule" /><div className="section-label">A GOOD PLACE TO START</div><div className="featured-list">{FEATURED.map((f, i) => { const Icon = [Heart, Brain, Activity, Leaf][i]; return <button key={f.name} onClick={() => chooseName(f.name)}><span className={`featured-icon featured-${i}`}><Icon size={22} strokeWidth={1.3} /></span><span><strong>{f.label}</strong><small>{f.description}</small></span><ArrowRight size={15} /></button>; })}</div><div className="memory-intro"><span><span className="tiny-dot" />BUILT AROUND YOU</span><p>Your anatomy is the starting point.<br />Your memories make it personal.</p><button onClick={() => { setPanel('memories'); }}>Explore body memory<ArrowRight size={13} /></button></div></div>}
          {chosen && panel === 'overview' && <><div className="system-label" style={{ color: system?.color }}><span style={{ background: system?.color }} />{system?.name ?? 'Anatomy'}</div><h2 className="structure-heading">{chosen.name}</h2><div className="structure-reference">{chosen.id}<span>·</span>{chosen.elements.length} modeled {chosen.elements.length === 1 ? 'piece' : 'pieces'}</div><div className="detail-tabs"><button className="active">Overview</button><button onClick={() => setPanel('memories')}>Memories<span>{relevantMemories.length}</span></button></div><p className="anatomy-description">{selectedPart ? explanation(chosen.name, selectedPart.system) : ''}</p>{!EXPLANATIONS[chosen.name.toLowerCase()] && <span className="context-caption">About this anatomical system</span>}<div className="detail-info"><span>Reference anatomy<strong>Adult human · Male</strong></span><span>Source<strong>BodyParts3D</strong></span></div>{chosen.elements.length > 1 && <div className="included-structures"><span className="section-label">INCLUDED STRUCTURES</span>{chosen.elements.slice(0, 8).map(id => <button key={id} onClick={() => choosePart(id)}><span>{parts.get(id)?.name}</span><ChevronRight size={12} /></button>)}{chosen.elements.length > 8 && <small>+ {chosen.elements.length - 8} more modeled pieces</small>}</div>}<button className="add-memory-card" onClick={() => { setNote(''); setModal('note'); }}><span><Plus size={17} /></span><div><strong>Start a body memory</strong><small>Add a note to this structure</small></div><ArrowRight size={15} /></button></>}
          {panel !== 'overview' && <div className="memories-panel">{chosen && <button className="back-link" onClick={() => setPanel('overview')}><ArrowLeft size={14} />{chosen.name}</button>}<h2>{panel === 'timeline' ? 'Your body’s story.' : chosen ? 'Connected memories.' : 'A memory of you.'}</h2><p className="panel-description">{panel === 'timeline' ? 'The moments you save, connected through time.' : 'Personal notes connected to the exact structures you choose.'}</p>{relevantMemories.length === 0 ? <div className="memory-empty"><span><StickyNote size={28} strokeWidth={1.2} /></span><h3>Your story starts here</h3><p>Select any structure, then add a note. It will stay connected to that part of your body.</p>{chosen ? <button className="primary-button" onClick={() => setModal('note')}><Plus size={15} />Add your first memory</button> : <button className="primary-button" onClick={() => chooseName('heart')}><Focus size={15} />Explore a structure</button>}</div> : <><div className={`memory-list ${panel === 'timeline' ? 'timeline-list' : ''}`}>{relevantMemories.map(m => <article className="memory-item" key={m.id}><div className="memory-meta"><time dateTime={m.createdAt}>{new Date(m.createdAt).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}</time><button className="remove-memory" aria-label={`Remove memory for ${m.concept.name}`} title="Remove memory" onClick={() => removeMemory(m.id)}><X size={12} /></button></div><button onClick={() => choose(m.concept, true)}>{m.concept.name}<ArrowRight size={13} /></button><p>{m.text}</p><span><StickyNote size={11} />Personal note</span></article>)}</div><button className="secondary-button export-button" onClick={exportMemories}><ArrowDownToLine size={15} />Export memories</button>{chosen && <button className="primary-button" onClick={() => setModal('note')}><Plus size={15} />Add memory</button>}</>}<div className="local-storage-note"><ShieldCheck size={14} /><span>Saved in this browser on this device.<br />Export to keep a separate copy.</span></div></div>}
        </div>
        {chosen && panel === 'overview' ? <div className="inspector-actions"><button className="primary-button" onClick={() => setState(s => ({ ...s, isolate: !s.isolate, explode: 0, zoom: 1 }))}><Focus size={16} />{state.isolate ? 'Show surrounding anatomy' : 'Isolate structure'}</button><div><button onClick={() => { setState(s => ({ ...s, hidden: [...new Set([...(s.hidden ?? []), ...chosen.elements])], selected: [], isolate: false, explode: 0 })); setChosen(null); }}><EyeOff size={14} />Hide</button><button onClick={clearSelection}><X size={14} />Clear selection</button></div></div> : <div className="inspector-hint"><MousePointer2 size={16} /><p>Select the model to inspect a structure.<br />There’s more beneath the surface.</p></div>}
      </aside>
    </div>
    <footer className="app-footer"><span><span className="tiny-dot" />A living map of the human body</span><span>BodyParts3D reference anatomy<span className="footer-separator">/</span><button onClick={() => setModal('credits')}>Made for exploration<ArrowRight size={11} /></button></span></footer>
    {toast && <div className="toast" role="status"><Check size={16} />{toast}</div>}
    {backendLoaded && <Suspense fallback={backendOpen ? <div className="toast" role="status">Loading records workspace…<button aria-label="Cancel opening records" onClick={() => setBackendOpen(false)}><X size={15} /></button></div> : null}><BackendPanel open={backendOpen} selectedConcept={chosen} onClose={() => setBackendOpen(false)} onSelectConcept={concept => choose(concept, true)} /></Suspense>}
    {modal === 'note' && chosen && <Modal title="Add a body memory" onClose={() => setModal(null)}><div className="note-structure"><Focus size={16} />{chosen.name}</div><p className="modal-description">A personal note, connected to this structure. Saved only in this browser.</p><form onSubmit={e => { e.preventDefault(); saveNote(); }}><label className="note-label" htmlFor="memory-note">Your note</label><textarea id="memory-note" autoFocus placeholder="What would you like to remember?" value={note} onChange={e => setNote(e.target.value)} maxLength={5000} required /><div className="modal-actions"><button className="secondary-button" type="button" onClick={() => setModal(null)}>Cancel</button><button className="primary-button" type="submit" disabled={!note.trim()}><Plus size={15} />Save memory</button></div></form></Modal>}
    {modal === 'help' && <Modal title="Make yourself at home" onClose={() => setModal(null)}><p className="modal-description">Explore the atlas with your mouse, keyboard, or touch.</p><div className="shortcut-list">{[['Orbit the body', 'Drag / arrow keys'], ['Pan the view', 'Right-drag / Shift + arrows'], ['Zoom', 'Scroll / + or −'], ['Find a structure', '/ or ⌘K / Ctrl K'], ['Reset the camera', 'Home'], ['Select center structure', 'Enter'], ['Close a panel', 'Escape']].map(([label, key]) => <div key={label}><span>{label}</span><kbd>{key}</kbd></div>)}</div><p className="modal-description">Keyboard camera controls work when the 3D canvas has focus. Search, region lists, and all controls are also keyboard accessible.</p></Modal>}
    {modal === 'credits' && <Modal title="A body, beautifully connected." onClose={() => setModal(null)}><p className="modal-description">BodyBrain uses a real anatomical reference: {atlas?.parts.length.toLocaleString() ?? '2,234'} meshes and {atlas?.concepts.length.toLocaleString() ?? '3,432'} named concepts across 15 systems.</p><div className="credits-copy"><h3>The anatomy</h3><p>BodyParts3D © The Database Center for Life Science. Licensed under <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a>. An adult male reference; coverage does not include every structure or human variation.</p><h3>The explorer</h3><p>Built on the open-source <a href="https://github.com/ashemag/human-atlas" target="_blank" rel="noreferrer">Human Atlas</a> (MIT). Model geometry was simplified for the web. BodyBrain adds its own interface, interactions, and local body memories.</p><h3>Your personal workspace</h3><p>Quick notes and bookmarks stay in this browser. Reviewed records are saved by your local BodyBrain backend. Connected agents and memory providers use the configuration you choose. The anatomy is an educational reference; BodyBrain does not interpret raw scans.</p><a href="/ATTRIBUTION.md" target="_blank" rel="noreferrer">Full dataset attribution<ArrowRight size={13} /></a></div></Modal>}
  </main>;
}
