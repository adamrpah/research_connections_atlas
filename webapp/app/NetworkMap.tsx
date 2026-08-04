"use client";

import { PointerEvent, useMemo, useRef, useState } from "react";
import type { AtlasData, Selection } from "./types";
import ManuscriptMap from "./ManuscriptMap";

const COLORS = ["#e76f51", "#2a9d8f", "#e9c46a", "#457b9d", "#9b5de5", "#f28482", "#5f797b", "#c77dff", "#577590", "#f6bd60", "#43aa8b", "#bc6c25", "#6d597a", "#ee6c4d", "#588157", "#8d99ae", "#ef476f", "#7b8794"];
const WIDTH = 1200, HEIGHT = 820, CX = WIDTH / 2, CY = HEIGHT / 2;

function hash(value: string) {
  let output = 0;
  for (let i = 0; i < value.length; i++) output = (output * 31 + value.charCodeAt(i)) >>> 0;
  return output;
}

export default function NetworkMap({ data, view, selection, similarityThreshold, onSelect }: { data: AtlasData; view: "themes" | "manuscripts" | "connections"; selection: Selection; similarityThreshold: number; onSelect: (value: Selection) => void }) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [panning, setPanning] = useState(false);
  const pointer = useRef<{ id: number; x: number; y: number } | null>(null);
  const topicIndex = useMemo(() => new Map(data.topics.map((topic, index) => [topic.id, index])), [data.topics]);
  const dominantTopic = useMemo(() => {
    const map = new Map<string, string>();
    data.faculty.forEach(faculty => {
      const edges = data.facultyTopicEdges.filter(edge => edge.source === faculty.id).sort((a, b) => b.publication_count - a.publication_count);
      map.set(faculty.id, edges[0]?.target ?? "topic_unclustered");
    });
    return map;
  }, [data]);
  const positions = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>();
    data.topics.forEach((topic, index) => {
      const angle = (index / data.topics.length) * Math.PI * 2 - Math.PI / 2;
      map.set(topic.id, { x: CX + Math.cos(angle) * 290, y: CY + Math.sin(angle) * 290 });
    });
    const grouped = new Map<string, string[]>();
    data.faculty.forEach(faculty => {
      const topic = dominantTopic.get(faculty.id) ?? "topic_unclustered";
      grouped.set(topic, [...(grouped.get(topic) ?? []), faculty.id]);
    });
    grouped.forEach((ids, topicId) => {
      const topic = map.get(topicId) ?? { x: CX, y: CY };
      ids.forEach((id, index) => {
        const base = Math.atan2(topic.y - CY, topic.x - CX);
        const spread = ids.length > 1 ? (index / (ids.length - 1) - 0.5) * 0.9 : 0;
        const radius = 72 + (hash(id) % 70);
        map.set(id, { x: topic.x + Math.cos(base + spread) * radius, y: topic.y + Math.sin(base + spread) * radius });
      });
    });
    return map;
  }, [data, dominantTopic]);

  const selectedNeighbors = useMemo(() => {
    if (!selection) return new Set<string>();
    const set = new Set<string>([selection.id]);
    if (view === "themes") data.facultyTopicEdges.forEach(edge => { if (edge.source === selection.id || edge.target === selection.id) { set.add(edge.source); set.add(edge.target); } });
    else data.similarityEdges.forEach(edge => { if (edge.source === selection.id || edge.target === selection.id) { set.add(edge.source); set.add(edge.target); } });
    return set;
  }, [data, selection, view]);

  const visibleSimilarity = data.similarityEdges.filter(edge => edge.combined_similarity >= similarityThreshold && (!selection || selection.type !== "faculty" || edge.source === selection.id || edge.target === selection.id));
  if (view === "manuscripts") return <ManuscriptMap data={data} selection={selection} onSelect={onSelect}/>;
  const viewWidth = WIDTH / zoom, viewHeight = HEIGHT / zoom;
  const viewBox = `${CX + pan.x - viewWidth / 2} ${CY + pan.y - viewHeight / 2} ${viewWidth} ${viewHeight}`;
  const startPan = (event: PointerEvent<SVGSVGElement>) => {
    if ((event.target as Element).closest(".node")) return;
    pointer.current = { id: event.pointerId, x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture(event.pointerId);
    setPanning(true);
  };
  const movePan = (event: PointerEvent<SVGSVGElement>) => {
    if (!pointer.current || pointer.current.id !== event.pointerId) return;
    const box = event.currentTarget.getBoundingClientRect();
    const dx = (event.clientX - pointer.current.x) * viewWidth / box.width;
    const dy = (event.clientY - pointer.current.y) * viewHeight / box.height;
    pointer.current = { id: event.pointerId, x: event.clientX, y: event.clientY };
    setPan(value => ({ x: value.x - dx, y: value.y - dy }));
  };
  const stopPan = (event: PointerEvent<SVGSVGElement>) => {
    if (pointer.current?.id === event.pointerId) pointer.current = null;
    setPanning(false);
  };
  const recenter = () => { setZoom(1); setPan({ x: 0, y: 0 }); };

  return <div className="network-wrap">
    <svg className={`network-svg pannable ${panning ? "is-panning" : ""}`} viewBox={viewBox} onPointerDown={startPan} onPointerMove={movePan} onPointerUp={stopPan} onPointerCancel={stopPan} role="img" aria-label={view === "themes" ? "Faculty and research theme network" : "Faculty research similarity network"}>
      <g className="network-lines">
        {view === "themes" ? data.facultyTopicEdges.map(edge => {
          const a = positions.get(edge.source), b = positions.get(edge.target); if (!a || !b) return null;
          const active = !selection || selectedNeighbors.has(edge.source) && selectedNeighbors.has(edge.target);
          return <line key={edge.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} strokeWidth={0.35 + Math.sqrt(edge.publication_count) * 0.65} className={active ? "active-edge" : "muted-edge"}/>;
        }) : visibleSimilarity.map(edge => {
          const a = positions.get(edge.source), b = positions.get(edge.target); if (!a || !b) return null;
          return <line key={edge.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} strokeWidth={0.4 + edge.combined_similarity * 1.6} className="similarity-edge"/>;
        })}
      </g>
      {view === "themes" && data.topics.map((topic, index) => {
        const p = positions.get(topic.id)!; const selected = selection?.id === topic.id; const muted = selection && !selectedNeighbors.has(topic.id);
        return <g key={topic.id} transform={`translate(${p.x} ${p.y})`} className={`node topic-node ${selected ? "selected" : ""} ${muted ? "muted" : ""}`} onClick={() => onSelect({ type: "topic", id: topic.id })} onMouseEnter={() => setHovered(topic.id)} onMouseLeave={() => setHovered(null)} role="button" tabIndex={0}>
          <circle r={selected ? 19 : 14 + Math.min(8, Math.sqrt(topic.publication_count) / 2)} fill={COLORS[index % COLORS.length]}/><circle className="node-ring" r={selected ? 25 : 21}/>
          {(hovered === topic.id || selected) && <g className="node-label"><rect x="-90" y="28" width="180" height="34" rx="8"/><text y="49" textAnchor="middle">{topic.label.length > 27 ? `${topic.label.slice(0, 27)}…` : topic.label}</text></g>}
        </g>;
      })}
      {data.faculty.map(faculty => {
        const p = positions.get(faculty.id)!; const selected = selection?.id === faculty.id; const muted = selection && !selectedNeighbors.has(faculty.id);
        const color = COLORS[(topicIndex.get(dominantTopic.get(faculty.id) ?? "") ?? 0) % COLORS.length];
        return <g key={faculty.id} transform={`translate(${p.x} ${p.y})`} className={`node faculty-node ${selected ? "selected" : ""} ${muted ? "muted" : ""}`} onClick={() => onSelect({ type: "faculty", id: faculty.id })} onMouseEnter={() => setHovered(faculty.id)} onMouseLeave={() => setHovered(null)} role="button" tabIndex={0}>
          <circle r={selected ? 11 : 5.5} fill={view === "connections" ? color : "#f7f2e8"}/><circle className="node-ring" r={selected ? 16 : 10}/>
          {(hovered === faculty.id || selected) && <g className="node-label"><rect x="-72" y="16" width="144" height="30" rx="7"/><text y="35" textAnchor="middle">{faculty.display_name}</text></g>}
        </g>;
      })}
    </svg>
    <div className="zoom-control"><button onClick={() => setZoom(z => Math.max(0.75, z - 0.15))} aria-label="Zoom out">−</button><button className="recenter-button" onClick={recenter} aria-label="Re-center network at 100%"><span>◎</span><small>{Math.round(zoom * 100)}%</small></button><button onClick={() => setZoom(z => Math.min(1.7, z + 0.15))} aria-label="Zoom in">+</button></div>
  </div>;
}
