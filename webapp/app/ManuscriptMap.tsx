"use client";

import { PointerEvent, useMemo, useRef, useState } from "react";
import type { AtlasData, Selection } from "./types";

const COLORS = ["#e76f51", "#2a9d8f", "#e9c46a", "#457b9d", "#9b5de5", "#f28482", "#5f797b", "#c77dff", "#577590", "#f6bd60", "#43aa8b", "#bc6c25", "#6d597a", "#ee6c4d", "#588157", "#8d99ae", "#ef476f", "#7b8794"];
const WIDTH = 1200, HEIGHT = 820, PAD = 62;

export default function ManuscriptMap({ data, selection, onSelect }: { data: AtlasData; selection: Selection; onSelect: (value: Selection) => void }) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [panning, setPanning] = useState(false);
  const pointer = useRef<{ id: number; x: number; y: number } | null>(null);
  const topicIndex = useMemo(() => new Map(data.topics.map((topic, index) => [topic.id, index])), [data.topics]);
  const positions = useMemo(() => {
    const xs = data.publications.map(item => item.coordinates.x), ys = data.publications.map(item => item.coordinates.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    return new Map(data.publications.map(item => [item.id, {
      x: PAD + ((item.coordinates.x - minX) / Math.max(maxX - minX, .001)) * (WIDTH - PAD * 2),
      y: PAD + ((item.coordinates.y - minY) / Math.max(maxY - minY, .001)) * (HEIGHT - PAD * 2),
    }]));
  }, [data.publications]);
  const selectedPublication = selection?.type === "publication" ? data.publications.find(item => item.id === selection.id) : null;
  const relatedIds = useMemo(() => {
    if (!selection) return new Set<string>();
    if (selection.type === "publication") {
      const paper = data.publications.find(item => item.id === selection.id);
      if (!paper) return new Set<string>();
      return new Set(data.publications.filter(item => item.topic_id === paper.topic_id || item.faculty_ids.some(id => paper.faculty_ids.includes(id))).map(item => item.id));
    }
    if (selection.type === "faculty") return new Set(data.publications.filter(item => item.faculty_ids.includes(selection.id)).map(item => item.id));
    return new Set(data.publications.filter(item => item.topic_id === selection.id).map(item => item.id));
  }, [data.publications, selection]);
  const relatedLines = selectedPublication ? data.publications.filter(item => item.id !== selectedPublication.id && relatedIds.has(item.id)).sort((a, b) => {
    const aFaculty = a.faculty_ids.some(id => selectedPublication.faculty_ids.includes(id)) ? 1 : 0;
    const bFaculty = b.faculty_ids.some(id => selectedPublication.faculty_ids.includes(id)) ? 1 : 0;
    return bFaculty - aFaculty || b.topic_probability - a.topic_probability;
  }).slice(0, 40) : [];
  const viewWidth = WIDTH / zoom, viewHeight = HEIGHT / zoom;
  const startPan = (event: PointerEvent<SVGSVGElement>) => {
    if ((event.target as Element).closest(".manuscript-node")) return;
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

  return <div className="network-wrap manuscript-wrap">
    <svg className={`network-svg manuscript-svg pannable ${panning ? "is-panning" : ""}`} viewBox={`${WIDTH / 2 + pan.x - viewWidth / 2} ${HEIGHT / 2 + pan.y - viewHeight / 2} ${viewWidth} ${viewHeight}`} onPointerDown={startPan} onPointerMove={movePan} onPointerUp={stopPan} onPointerCancel={stopPan} role="img" aria-label="Map of individual manuscripts positioned by research-text similarity">
      {selectedPublication && relatedLines.map(item => { const a = positions.get(selectedPublication.id)!, b = positions.get(item.id)!; const sharesFaculty = item.faculty_ids.some(id => selectedPublication.faculty_ids.includes(id)); return <line key={item.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={sharesFaculty ? "manuscript-faculty-link" : "manuscript-topic-link"}/>; })}
      {data.publications.map(item => {
        const p = positions.get(item.id)!; const selected = selection?.type === "publication" && selection.id === item.id; const active = !selection || relatedIds.has(item.id); const topic = topicIndex.get(item.topic_id) ?? 17;
        return <g key={item.id} transform={`translate(${p.x} ${p.y})`} className={`manuscript-node ${selected ? "selected" : ""} ${active ? "" : "muted"}`} onClick={() => onSelect({ type: "publication", id: item.id })} onMouseEnter={() => setHovered(item.id)} onMouseLeave={() => setHovered(null)} role="button" tabIndex={0}>
          <circle r={selected ? 9 : active && selection ? 4.2 : 2.8} fill={COLORS[topic % COLORS.length]}/>{selected && <circle className="manuscript-ring" r="15"/>}
          {(hovered === item.id || selected) && <g className="node-label manuscript-label"><rect x="-115" y="15" width="230" height="43" rx="8"/><text y="32" textAnchor="middle">{item.title.length > 38 ? `${item.title.slice(0, 38)}…` : item.title}</text><text className="label-meta" y="47" textAnchor="middle">{item.publication_year ?? "Year unavailable"} · {data.topics.find(x => x.id === item.topic_id)?.label.slice(0, 28)}</text></g>}
        </g>;
      })}
    </svg>
    <div className="manuscript-key"><strong>Manuscript landscape</strong><span>Nearby papers use similar language in their titles and abstracts.</span>{selectedPublication && <small><i/> solid lines share attributed faculty · <b/> dotted lines share a topic</small>}</div>
    <div className="zoom-control"><button onClick={() => setZoom(z => Math.max(.8, z - .15))} aria-label="Zoom out">−</button><button className="recenter-button" onClick={recenter} aria-label="Re-center manuscript map at 100%"><span>◎</span><small>{Math.round(zoom * 100)}%</small></button><button onClick={() => setZoom(z => Math.min(2.1, z + .15))} aria-label="Zoom in">+</button></div>
  </div>;
}
