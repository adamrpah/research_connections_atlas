"use client";

import { useEffect, useMemo, useState } from "react";
import type { AtlasData, Faculty, FacultyProfile, FacultyTopicEdge, Publication, Selection, SimilarityEdge, Topic } from "./types";
import NetworkMap from "./NetworkMap";
import DetailPanel from "./DetailPanel";
import FeedbackDialog from "./FeedbackDialog";
import AbstractMatcher from "./AbstractMatcher";

type ViewMode = "themes" | "manuscripts" | "connections" | "match";
type SearchResult = { type: "faculty" | "topic" | "publication"; id: string; title: string; meta: string };

const formatCount = new Intl.NumberFormat("en-US").format;

async function loadJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return response.json() as Promise<T>;
}

export default function AtlasApp() {
  const [data, setData] = useState<AtlasData | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<ViewMode>("themes");
  const [selection, setSelection] = useState<Selection>(null);
  const [query, setQuery] = useState("");
  const [similarity, setSimilarity] = useState(0.72);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const handleSelect = (value: Selection) => {
    setSelection(value);
    if (value?.type === "publication") setView("manuscripts");
  };

  useEffect(() => {
    Promise.all([
      loadJson<Faculty[]>("/data/faculty.json"), loadJson<Topic[]>("/data/topics.json"),
      loadJson<FacultyProfile[]>("/data/faculty_profiles.json"), loadJson<FacultyTopicEdge[]>("/data/faculty_topic_edges.json"),
      loadJson<SimilarityEdge[]>("/data/faculty_similarity_edges.json"), loadJson<Publication[]>("/data/publications.json"),
    ]).then(([faculty, topics, profiles, facultyTopicEdges, similarityEdges, publications]) => {
      setData({ faculty, topics, profiles, facultyTopicEdges, similarityEdges, publications });
    }).catch(() => setError("The research data could not be loaded. Please refresh and try again."));
  }, []);

  const results = useMemo<SearchResult[]>(() => {
    if (!data || query.trim().length < 2) return [];
    const terms = query.toLowerCase().trim().split(/\s+/);
    const score = (value: string) => terms.reduce((total, term) => total + (value.includes(term) ? 1 : 0), 0);
    const rows: (SearchResult & { score: number })[] = [];
    data.faculty.forEach(item => {
      const value = [item.display_name, ...item.aliases].join(" ").toLowerCase();
      const rank = score(value); if (rank) rows.push({ type: "faculty", id: item.id, title: item.display_name, meta: "Faculty", score: rank + 2 });
    });
    data.topics.forEach(item => {
      const value = [item.label, item.description, ...item.top_terms].join(" ").toLowerCase();
      const rank = score(value); if (rank) rows.push({ type: "topic", id: item.id, title: item.label, meta: `${item.publication_count} publications`, score: rank + 3 });
    });
    data.publications.forEach(item => {
      const value = [item.title, item.abstract ?? "", ...item.authors].join(" ").toLowerCase();
      const rank = score(value); if (rank) rows.push({ type: "publication", id: item.id, title: item.title, meta: item.publication_year ? `Publication · ${item.publication_year}` : "Publication", score: rank });
    });
    return rows.sort((a, b) => b.score - a.score || a.title.localeCompare(b.title)).slice(0, 12).map(item => ({ type: item.type, id: item.id, title: item.title, meta: item.meta }));
  }, [data, query]);

  const selectResult = (item: SearchResult) => {
    setSelection({ type: item.type, id: item.id });
    setQuery("");
    if (item.type === "publication") setView("manuscripts");
    else if (item.type === "faculty" && view !== "connections") setView("themes");
  };

  if (error) return <main className="state-screen"><p className="eyebrow">Research Connections Atlas</p><h1>We hit a snag.</h1><p>{error}</p></main>;
  if (!data) return <main className="state-screen" role="status"><span className="loader"/><p className="eyebrow">Research Connections Atlas</p><h1>Mapping the research landscape…</h1></main>;

  const selectedLabel = selection ? (selection.type === "faculty" ? data.faculty.find(x => x.id === selection.id)?.display_name : selection.type === "topic" ? data.topics.find(x => x.id === selection.id)?.label : data.publications.find(x => x.id === selection.id)?.title) : "Research atlas";
  const corpusCounts = {
    faculty: formatCount(data.faculty.length),
    topics: formatCount(data.topics.length),
    publications: formatCount(data.publications.length),
    facultyTopicLinks: formatCount(data.facultyTopicEdges.length),
  };

  return (
    <main className="atlas-shell">
      <header className="topbar">
        <button className="brand" onClick={() => setSelection(null)} aria-label="Reset atlas">
          <span className="brand-mark">RC</span><span><strong>Research Connections</strong><small>Faculty knowledge atlas</small></span>
        </button>
        <div className="search-wrap">
          <span className="search-icon">⌕</span>
          <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search a theme, faculty member, or paper…" aria-label="Search research atlas" />
          {query && <button className="clear-search" onClick={() => setQuery("")} aria-label="Clear search">×</button>}
          {results.length > 0 && <div className="search-results" role="listbox">
            {results.map(item => <button key={`${item.type}-${item.id}`} onClick={() => selectResult(item)}><span>{item.title}</span><small>{item.meta}</small></button>)}
          </div>}
        </div>
        <nav className="header-actions">
          <button className="text-button" onClick={() => setAboutOpen(true)}>How to read this</button>
          <button className="feedback-button" onClick={() => setFeedbackOpen(true)}>Give feedback</button>
        </nav>
      </header>

      <section className="workspace">
        <aside className="control-rail">
          <div><p className="eyebrow">Explore the network</p><h1>Where ideas<br/>find company.</h1><p className="intro">Trace faculty through shared themes, then surface promising connections grounded in their published work.</p></div>
          <div className="view-switch" aria-label="Network view">
            <button className={view === "themes" ? "active" : ""} onClick={() => setView("themes")}><span>◉</span><div><strong>Faculty × themes</strong><small>Bipartite topic network</small></div></button>
            <button className={view === "manuscripts" ? "active" : ""} onClick={() => setView("manuscripts")}><span>▤</span><div><strong>Manuscript landscape</strong><small>Every modeled paper</small></div></button>
            <button className={view === "connections" ? "active" : ""} onClick={() => setView("connections")}><span>⌁</span><div><strong>Potential connections</strong><small>Research similarity</small></div></button>
            <button className={view === "match" ? "active" : ""} onClick={() => { setView("match"); setSelection(null); }}><span>↗</span><div><strong>Match an abstract</strong><small>Find topics & faculty</small></div></button>
          </div>
          {view === "connections" && <label className="slider-control"><span><strong>Similarity threshold</strong><b>{Math.round(similarity * 100)}%</b></span><input type="range" min="0.35" max="0.9" step="0.01" value={similarity} onChange={e => setSimilarity(Number(e.target.value))}/><small>Higher values show only the closest research profiles.</small></label>}
          <div className="legend">
            <p className="eyebrow">Legend</p>
            <span><i className="topic-dot"/>{view === "manuscripts" ? "Manuscript, colored by theme" : "Research theme"}</span><span><i className="faculty-dot"/>Faculty member</span><span><i className="line-dot"/>{view === "themes" ? "Publication-weighted link" : view === "manuscripts" ? "Shared faculty or theme" : "Potential overlap"}</span>
          </div>
          <div className="corpus-note"><strong>{corpusCounts.publications}</strong><span>modeled publications<br/>across {corpusCounts.faculty} researchers</span></div>
        </aside>

        {view === "match" ? <AbstractMatcher data={data} onSelect={value => { setView("themes"); setSelection(value); }}/> : <section className="network-stage" aria-label="Interactive research network">
          <div className="stage-meta"><span>{view === "themes" ? `${corpusCounts.topics} themes · ${corpusCounts.facultyTopicLinks} faculty links` : view === "manuscripts" ? `${corpusCounts.publications} manuscripts · positioned by text similarity` : `${formatCount(data.similarityEdges.filter(x => x.combined_similarity >= similarity).length)} potential connections`}</span><span>Click any node to inspect</span></div>
          <NetworkMap data={data} view={view} selection={selection} similarityThreshold={similarity} onSelect={handleSelect}/>
          {!selection && <div className="stage-callout"><span>Start here</span><strong>Select a theme or faculty node</strong><small>Every relationship can be traced to publications and corrected through feedback.</small></div>}
        </section>}

        {view === "match" ? <aside className="detail-panel matcher-aside"><p className="eyebrow">How matching works</p><h2>A research-neighborhood signal.</h2><p className="topic-description">Your abstract is encoded with the same SPECTER2 proximity model used for the atlas corpus. Cosine similarity then identifies the closest topic centroids and faculty publication profiles.</p><div className="panel-section"><h3>Interpret with care</h3><p>Matches reflect similarity in published research—not availability, endorsement, or a recommendation to collaborate.</p></div><div className="panel-section"><h3>Privacy</h3><p>The abstract is sent only to the configured SPECTER2 service for this request and is not saved by the atlas.</p></div></aside> : <DetailPanel data={data} selection={selection} onSelect={handleSelect} onClose={() => setSelection(null)} onFeedback={() => setFeedbackOpen(true)}/>}
      </section>

      <footer><span>Research Connections Atlas</span><span>Connections indicate analytical similarity—not institutional recommendation.</span><button onClick={() => setAboutOpen(true)}>Methods & limitations</button></footer>

      {feedbackOpen && <FeedbackDialog selection={selection} targetLabel={selectedLabel ?? "Research atlas"} onClose={() => setFeedbackOpen(false)}/>} 
      {aboutOpen && <div className="modal-backdrop" onMouseDown={() => setAboutOpen(false)}><section className="about-modal" role="dialog" aria-modal="true" aria-labelledby="about-title" onMouseDown={e => e.stopPropagation()}><button className="modal-close" onClick={() => setAboutOpen(false)} aria-label="Close">×</button><p className="eyebrow">About the atlas</p><h2 id="about-title">A map of evidence, not a verdict.</h2><p>The atlas groups publications using their titles and abstracts, then connects faculty to those themes through annual-report attribution. Potential connections combine topic-profile overlap with similarity between publication-text embeddings.</p><div className="method-grid"><div><strong>Theme links</strong><span>Thickness reflects the number of attributed publications.</span></div><div><strong>Potential connections</strong><span>Scores indicate research similarity, not collaboration.</span></div><div><strong>Your feedback</strong><span>Corrections are stored for future improvements to the analytical pipeline.</span></div></div><p className="fine-print">The current data does not yet resolve every coauthor. Unclustered work remains visible and can receive feedback.</p></section></div>}
    </main>
  );
}
