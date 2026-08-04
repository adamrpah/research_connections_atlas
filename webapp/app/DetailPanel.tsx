"use client";

import { useState } from "react";
import type { AtlasData, Selection } from "./types";

export default function DetailPanel({ data, selection, onSelect, onClose, onFeedback }: { data: AtlasData; selection: Selection; onSelect: (value: Selection) => void; onClose: () => void; onFeedback: () => void }) {
  const [topicFacultyFocus, setTopicFacultyFocus] = useState<{ topicId: string; facultyId: string } | null>(null);
  if (!selection) return <aside className="detail-panel detail-empty"><div className="empty-orbit"><span/><span/><i/></div><p className="eyebrow">Selection details</p><h2>Choose a point<br/>in the network.</h2><p>Inspect its evidence, neighboring themes, and the publications behind each connection.</p></aside>;
  if (selection.type === "faculty") {
    const faculty = data.faculty.find(x => x.id === selection.id)!;
    const profile = data.profiles.find(x => x.faculty_id === selection.id);
    const topicEdges = data.facultyTopicEdges.filter(x => x.source === selection.id).sort((a, b) => b.publication_count - a.publication_count);
    const publications = data.publications.filter(x => x.faculty_ids.includes(selection.id)).sort((a, b) => (b.publication_year ?? 0) - (a.publication_year ?? 0));
    const connections = data.similarityEdges.filter(x => x.source === selection.id || x.target === selection.id).sort((a, b) => b.combined_similarity - a.combined_similarity).slice(0, 5);
    return <aside className="detail-panel"><PanelHeader onClose={onClose}/><p className="eyebrow">Faculty profile</p><h2>{faculty.display_name}</h2><p className="panel-meta">{profile?.publication_count ?? publications.length} modeled publications · {topicEdges.length} research themes</p>
      <section className="panel-section"><h3>Research signature</h3>{topicEdges.slice(0, 6).map(edge => { const topic = data.topics.find(x => x.id === edge.target)!; return <button className="topic-bar" key={edge.id} onClick={() => onSelect({ type: "topic", id: topic.id })}><span><b>{topic.label}</b><small>{edge.publication_count} papers</small></span><i style={{ width: `${Math.max(8, edge.share_of_faculty_clustered_publications * 100)}%` }}/></button>; })}</section>
      <section className="panel-section"><h3>Closest research neighbors</h3>{connections.map(edge => { const otherId = edge.source === selection.id ? edge.target : edge.source; const other = data.faculty.find(x => x.id === otherId)!; return <button className="neighbor-row" key={edge.id} onClick={() => onSelect({ type: "faculty", id: otherId })}><span className="avatar">{other.display_name.split(" ").map(x => x[0]).slice(0, 2).join("")}</span><span><b>{other.display_name}</b><small>{edge.explanation}</small></span><strong>{Math.round(edge.combined_similarity * 100)}%</strong></button>; })}</section>
      <PublicationList publications={publications} onSelect={onSelect}/><FeedbackPrompt label="Is this profile attributed correctly?" onFeedback={onFeedback}/>
    </aside>;
  }
  if (selection.type === "topic") {
    const topic = data.topics.find(x => x.id === selection.id)!;
    const edges = data.facultyTopicEdges.filter(x => x.target === selection.id).sort((a, b) => b.publication_count - a.publication_count);
    const publications = data.publications.filter(x => x.topic_id === selection.id).sort((a, b) => b.topic_probability - a.topic_probability);
    const topicFacultyId = topicFacultyFocus?.topicId === topic.id ? topicFacultyFocus.facultyId : null;
    const focusedFaculty = topicFacultyId ? data.faculty.find(x => x.id === topicFacultyId) : null;
    const focusedPublications = focusedFaculty ? publications.filter(item => item.faculty_ids.includes(focusedFaculty.id)).sort((a, b) => (b.publication_year ?? 0) - (a.publication_year ?? 0)) : [];
    return <aside className="detail-panel"><PanelHeader onClose={onClose}/><p className="eyebrow">Research theme</p><h2>{topic.label}</h2><p className="topic-description">{topic.description}</p><div className="stat-row"><span><strong>{topic.publication_count}</strong><small>publications</small></span><span><strong>{edges.length}</strong><small>faculty</small></span></div>
      {topic.top_terms.length > 0 && <section className="panel-section"><h3>Signal terms</h3><div className="term-cloud">{topic.top_terms.slice(0, 10).map(term => <span key={term}>{term}</span>)}</div></section>}
      <section className="panel-section"><h3>Faculty active here <span>Select to see papers</span></h3>{edges.slice(0, 8).map(edge => { const faculty = data.faculty.find(x => x.id === edge.source)!; return <button className={`faculty-rank ${topicFacultyId === faculty.id ? "active" : ""}`} key={edge.id} onClick={() => setTopicFacultyFocus({ topicId: topic.id, facultyId: faculty.id })}><span>{faculty.display_name}</span><b>{edge.publication_count}</b></button>; })}</section>
      {focusedFaculty ? <section className="panel-section faculty-topic-evidence"><button className="evidence-back" onClick={() => setTopicFacultyFocus(null)}>← All topic manuscripts</button><p className="eyebrow">Faculty × topic evidence</p><h3>{focusedFaculty.display_name}</h3><p className="connection-note">{focusedPublications.length} manuscript{focusedPublications.length === 1 ? "" : "s"} connect {focusedFaculty.display_name} to this topic.</p>{focusedPublications.map(item => <button className="paper-row" key={item.id} onClick={() => onSelect({ type: "publication", id: item.id })}><span>{item.title}</span><small>{item.publication_year ?? "Year unavailable"} · {Math.round(item.topic_probability * 100)}% topic confidence</small></button>)}<button className="profile-link" onClick={() => onSelect({ type: "faculty", id: focusedFaculty.id })}>View full faculty profile ↗</button></section> : <PublicationList publications={publications} onSelect={onSelect}/>}<FeedbackPrompt label="Does this topic label fit the papers?" onFeedback={onFeedback}/>
    </aside>;
  }
  const publication = data.publications.find(x => x.id === selection.id)!;
  const topic = data.topics.find(x => x.id === publication.topic_id)!;
  const related = data.publications.filter(item => item.id !== publication.id && (item.topic_id === publication.topic_id || item.faculty_ids.some(id => publication.faculty_ids.includes(id)))).sort((a, b) => {
    const aFaculty = a.faculty_ids.some(id => publication.faculty_ids.includes(id)) ? 1 : 0;
    const bFaculty = b.faculty_ids.some(id => publication.faculty_ids.includes(id)) ? 1 : 0;
    return bFaculty - aFaculty || b.topic_probability - a.topic_probability;
  });
  return <aside className="detail-panel"><PanelHeader onClose={onClose}/><p className="eyebrow">Publication</p><h2 className="publication-title">{publication.title}</h2><p className="panel-meta">{publication.publication_year ?? "Year unavailable"} · Topic confidence {Math.round(publication.topic_probability * 100)}%</p>
    <button className="topic-pill" onClick={() => onSelect({ type: "topic", id: topic.id })}>{topic.label}</button>
    <section className="panel-section"><h3>Authors</h3><p>{publication.authors.join(", ") || "Author metadata unavailable"}</p></section>
    {publication.abstract && <section className="panel-section"><h3>Abstract</h3><p className="abstract">{publication.abstract}</p></section>}
    {publication.faculty_ids.length > 0 && <section className="panel-section"><h3>Attributed faculty</h3>{publication.faculty_ids.map(id => { const faculty = data.faculty.find(x => x.id === id)!; return <button className="faculty-rank" key={id} onClick={() => onSelect({ type: "faculty", id })}><span>{faculty.display_name}</span><b>↗</b></button>; })}</section>}
    <section className="panel-section"><h3>Connected manuscripts <span>{related.length}</span></h3><p className="connection-note">Related through shared faculty or the same modeled research theme.</p>{related.slice(0, 6).map(item => <button className="paper-row" key={item.id} onClick={() => onSelect({ type: "publication", id: item.id })}><span>{item.title}</span><small>{item.faculty_ids.some(id => publication.faculty_ids.includes(id)) ? "Shared attributed faculty" : `Shared theme · ${topic.label}`}</small></button>)}</section>
    {publication.landing_url && <a className="source-link" href={publication.landing_url} target="_blank" rel="noreferrer">Open publication source ↗</a>}<FeedbackPrompt label="Is this topic or faculty attribution wrong?" onFeedback={onFeedback}/>
  </aside>;
}

function PanelHeader({ onClose }: { onClose: () => void }) { return <button className="panel-close" onClick={onClose} aria-label="Close details">×</button>; }
function FeedbackPrompt({ label, onFeedback }: { label: string; onFeedback: () => void }) { return <div className="feedback-prompt"><span><strong>{label}</strong><small>Your correction improves the next model.</small></span><button onClick={onFeedback}>Report an issue</button></div>; }
function PublicationList({ publications, onSelect }: { publications: AtlasData["publications"]; onSelect: (value: Selection) => void }) { return <section className="panel-section"><h3>Publications <span>{publications.length}</span></h3>{publications.slice(0, 6).map(item => <button className="paper-row" key={item.id} onClick={() => onSelect({ type: "publication", id: item.id })}><span>{item.title}</span><small>{item.publication_year ?? "Year unavailable"} · {Math.round(item.topic_probability * 100)}% topic confidence</small></button>)}</section>; }
