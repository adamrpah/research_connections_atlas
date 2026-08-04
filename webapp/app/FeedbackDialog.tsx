"use client";

import { FormEvent, useState } from "react";
import type { Selection } from "./types";

const OPTIONS: Record<string, { value: string; label: string }[]> = {
  topic_quality: [{ value: "incorrect_topic", label: "Paper is in the wrong topic" }, { value: "unclear_label", label: "Topic label is unclear" }, { value: "incorrect_description", label: "Description is inaccurate" }, { value: "topic_too_broad", label: "Topic is too broad" }, { value: "topic_too_narrow", label: "Topic is too narrow" }, { value: "suggested_topic", label: "Suggest a different topic" }],
  attribution_error: [{ value: "wrong_faculty", label: "Wrong faculty attribution" }, { value: "missing_faculty", label: "Faculty member is missing" }, { value: "duplicate_faculty", label: "Duplicate faculty identity" }, { value: "name_error", label: "Faculty name is incorrect" }, { value: "wrong_publication", label: "Publication does not belong here" }],
  metadata_error: [{ value: "title", label: "Incorrect title" }, { value: "year", label: "Incorrect year" }, { value: "doi", label: "Incorrect DOI or link" }, { value: "authors", label: "Incorrect authors" }, { value: "abstract", label: "Incorrect abstract" }, { value: "url", label: "Broken source link" }],
};

export default function FeedbackDialog({ selection, targetLabel, onClose }: { selection: Selection; targetLabel: string; onClose: () => void }) {
  const initialCategory = selection?.type === "topic" ? "topic_quality" : "attribution_error";
  const [category, setCategory] = useState(initialCategory);
  const [kind, setKind] = useState(OPTIONS[initialCategory][0].value);
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [message, setMessage] = useState("");
  const changeCategory = (value: string) => { setCategory(value); setKind(OPTIONS[value][0].value); };
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setStatus("sending"); setMessage("");
    const form = new FormData(event.currentTarget);
    const response = await fetch("/api/feedback", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({
      targetType: selection?.type ?? "edge", targetId: selection?.id ?? "atlas_general", targetLabel,
      feedbackCategory: category, feedbackType: kind, comment: form.get("comment"), suggestedValue: form.get("suggestedValue"),
      contactEmail: form.get("contactEmail"), website: form.get("website"), pageUrl: window.location.href, datasetVersion: "1.0.0",
    }) });
    const result = await response.json() as { error?: string };
    if (!response.ok) { setStatus("error"); setMessage(result.error ?? "Feedback could not be saved."); } else setStatus("sent");
  }
  return <div className="modal-backdrop" onMouseDown={onClose}><section className="feedback-modal" role="dialog" aria-modal="true" aria-labelledby="feedback-title" onMouseDown={e => e.stopPropagation()}><button className="modal-close" onClick={onClose} aria-label="Close">×</button>
    {status === "sent" ? <div className="success-state"><span>✓</span><p className="eyebrow">Feedback received</p><h2>Thank you for improving the atlas.</h2><p>Your correction is stored and can inform the next analytical revision.</p><button onClick={onClose}>Return to the atlas</button></div> : <><p className="eyebrow">Community review</p><h2 id="feedback-title">Help us sharpen the map.</h2><p className="modal-intro">Reporting feedback about <strong>{targetLabel}</strong></p><form onSubmit={submit}>
      <label><span>What needs attention?</span><select value={category} onChange={e => changeCategory(e.target.value)}><option value="topic_quality">Topic or label quality</option><option value="attribution_error">Faculty attribution</option><option value="metadata_error">Publication metadata</option></select></label>
      <label><span>Issue</span><select value={kind} onChange={e => setKind(e.target.value)}>{OPTIONS[category].map(item => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label>
      <label><span>What should we know?</span><textarea name="comment" required minLength={10} maxLength={4000} placeholder="Describe what looks wrong and why…"/></label>
      <label><span>Suggested correction <small>optional</small></span><input name="suggestedValue" maxLength={2000} placeholder="A better label, faculty name, or topic…"/></label>
      <label><span>Email <small>optional, only for follow-up</small></span><input name="contactEmail" type="email" maxLength={254} placeholder="you@example.edu"/></label><input className="honeypot" name="website" tabIndex={-1} autoComplete="off"/>
      {status === "error" && <p className="form-error">{message}</p>}<button className="submit-feedback" disabled={status === "sending"}>{status === "sending" ? "Saving…" : "Submit feedback"}</button><p className="privacy-note">Feedback is stored with this dataset version. Email is optional and is not displayed publicly.</p>
    </form></>}
  </section></div>;
}
