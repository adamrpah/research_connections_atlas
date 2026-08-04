"use client";

import { FormEvent, useState } from "react";
import type { AtlasData, Selection } from "./types";

type Match = { id: string; score: number };
type MatchResponse = { topics: Match[]; faculty: Match[]; model: string };

export default function AbstractMatcher({ data, onSelect }: { data: AtlasData; onSelect: (selection: Selection) => void }) {
  const [abstract, setAbstract] = useState("");
  const [result, setResult] = useState<MatchResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const wordCount = abstract.trim() ? abstract.trim().split(/\s+/).length : 0;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (abstract.trim().length < 80) { setError("Please enter a fuller abstract (at least 80 characters)."); return; }
    setLoading(true);
    try {
      const response = await fetch("/api/match-abstract", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ abstract: abstract.trim() }) });
      const payload = await response.json() as MatchResponse & { error?: string };
      if (!response.ok) throw new Error(payload.error || "The abstract could not be matched.");
      setResult(payload);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "The abstract could not be matched."); }
    finally { setLoading(false); }
  }

  return <section className="matcher-stage" aria-labelledby="matcher-title">
    <div className="matcher-heading"><p className="eyebrow">SPECTER2 discovery</p><h2 id="matcher-title">Who might this research connect with?</h2><p>Paste a working abstract to find its closest themes and faculty research profiles in the atlas.</p></div>
    <form className="abstract-form" onSubmit={submit}>
      <label htmlFor="abstract-input">Research abstract</label>
      <textarea id="abstract-input" value={abstract} onChange={event => setAbstract(event.target.value)} maxLength={6000} placeholder="Paste the abstract here…"/>
      <div className="abstract-form-meta"><span>{wordCount} words · 6,000 character limit</span><button type="submit" disabled={loading || abstract.trim().length < 80}>{loading ? "Finding connections…" : "Find connections"}</button></div>
      {error && <p className="matcher-error" role="alert">{error}</p>}
    </form>
    {result && <div className="match-results" aria-live="polite">
      <section><div className="result-title"><p className="eyebrow">Closest themes</p><span>SPECTER2 similarity</span></div>{result.topics.map((match, index) => { const topic = data.topics.find(item => item.id === match.id); return topic && <button className="match-card topic-match" key={match.id} onClick={() => onSelect({ type: "topic", id: match.id })}><b>{String(index + 1).padStart(2, "0")}</b><span><strong>{topic.label}</strong><small>{topic.description}</small></span><em>{Math.round(match.score * 100)}%</em></button>; })}</section>
      <section><div className="result-title"><p className="eyebrow">Faculty connections</p><span>Research-profile similarity</span></div>{result.faculty.map((match, index) => { const faculty = data.faculty.find(item => item.id === match.id); const profile = data.profiles.find(item => item.faculty_id === match.id); return faculty && <button className="match-card faculty-match" key={match.id} onClick={() => onSelect({ type: "faculty", id: match.id })}><b>{String(index + 1).padStart(2, "0")}</b><span><strong>{faculty.display_name}</strong><small>{profile?.publication_count ?? 0} modeled publications · {profile?.topic_count ?? 0} themes</small></span><em>{Math.round(match.score * 100)}%</em></button>; })}</section>
    </div>}
  </section>;
}
