#!/usr/bin/env python3
"""Embed publication abstracts and discover research topics.

Default model: SPECTER2 base plus its proximity adapter. Outputs include reusable
embeddings, two-dimensional coordinates, HDBSCAN assignments, c-TF-IDF topic terms,
representative papers, and clustering QA metrics.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
from collections import Counter
from pathlib import Path

import hdbscan
import numpy as np
import pandas as pd
import torch
import umap
from adapters import AutoAdapterModel
from sklearn.feature_extraction.text import CountVectorizer, ENGLISH_STOP_WORDS
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize
from transformers import AutoTokenizer


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def device_name(requested: str) -> str:
    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_documents(path: Path, require_abstract: bool) -> pd.DataFrame:
    frame = pd.read_csv(path).fillna("")
    frame = frame[frame["match_status"] == "matched"].copy()
    if require_abstract:
        frame = frame[frame["abstract"].str.strip() != ""].copy()
    normalized = frame["canonical_title"].where(frame["canonical_title"] != "", frame["original_title"])
    normalized = normalized.str.lower().str.replace(r"[^a-z0-9]+", " ", regex=True).str.strip()
    frame["work_key"] = np.where(frame["doi"].str.strip() != "", "doi:" + frame["doi"].str.lower(),
                                 "title:" + normalized)
    frame["abstract_length"] = frame["abstract"].str.len()
    provenance = frame.groupby("work_key")["record_id"].agg(list).to_dict()
    frame = (frame.sort_values("abstract_length", ascending=False)
             .drop_duplicates("work_key", keep="first").copy())
    frame["source_record_ids"] = frame["work_key"].map(lambda key: ";".join(provenance[key]))
    frame["duplicate_record_count"] = frame["work_key"].map(lambda key: len(provenance[key]))
    frame["document_text"] = (
        "Title: " + frame["canonical_title"].where(frame["canonical_title"] != "", frame["original_title"])
        + "\nAbstract: " + frame["abstract"]
    )
    frame["input_quality"] = np.where(frame["abstract"].str.strip() != "", "title_and_abstract", "title_only")
    return frame.drop(columns=["abstract_length"]).reset_index(drop=True)


def specter2_embeddings(texts: list[str], model_name: str, adapter_name: str,
                        batch_size: int, device: str, max_length: int) -> np.ndarray:
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoAdapterModel.from_pretrained(model_name)
    loaded_adapter = model.load_adapter(adapter_name, source="hf", set_active=False)
    model.set_active_adapters(loaded_adapter)
    if not model.active_adapters:
        raise RuntimeError("SPECTER2 adapter failed to activate")
    print(f"active_adapter={model.active_adapters}", flush=True)
    model.to(device)
    model.eval()
    batches = []
    with torch.inference_mode():
        for start in range(0, len(texts), batch_size):
            tokens = tokenizer(texts[start:start + batch_size], padding=True, truncation=True,
                               max_length=max_length, return_tensors="pt")
            tokens = {key: value.to(device) for key, value in tokens.items()}
            output = model(**tokens)
            # SPECTER2 uses the contextual representation of the first token.
            vectors = output.last_hidden_state[:, 0, :]
            vectors = torch.nn.functional.normalize(vectors, p=2, dim=1)
            batches.append(vectors.detach().cpu().float().numpy())
            print(f"embedded {min(start + batch_size, len(texts))}/{len(texts)}", flush=True)
    return np.vstack(batches)


def topic_terms(documents: list[str], labels: np.ndarray, top_n: int) -> dict[int, list[tuple[str, float]]]:
    topic_ids = sorted(label for label in set(labels.tolist()) if label >= 0)
    joined = [" ".join(documents[i] for i in np.where(labels == topic)[0]) for topic in topic_ids]
    # Each input row here is an aggregated topic, so terms appearing in only one topic
    # are informative rather than rare-document noise.
    stop_words = sorted(set(ENGLISH_STOP_WORDS) | {"title", "abstract"})
    vectorizer = CountVectorizer(stop_words=stop_words, ngram_range=(1, 2), min_df=1, max_df=1.0)
    counts = vectorizer.fit_transform(joined).astype(float)
    tf = normalize(counts, norm="l1", axis=1)
    document_frequency = np.asarray((counts > 0).sum(axis=0)).ravel()
    idf = np.log((1 + len(topic_ids)) / (1 + document_frequency)) + 1
    scores = tf.multiply(idf)
    vocabulary = np.asarray(vectorizer.get_feature_names_out())
    output = {}
    for row, topic in enumerate(topic_ids):
        values = scores.getrow(row).toarray().ravel()
        best = values.argsort()[::-1][:top_n]
        output[topic] = [(vocabulary[i], round(float(values[i]), 6)) for i in best if values[i] > 0]
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path,
                        default=Path("results/publication_resolution/publication_resolution.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/topic_model_specter2"))
    parser.add_argument("--model", default="allenai/specter2_base")
    parser.add_argument("--adapter", default="allenai/specter2")
    parser.add_argument("--device", choices=["auto", "cpu", "mps", "cuda"], default="auto")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--min-cluster-size", type=int, default=20)
    parser.add_argument("--min-samples", type=int, default=8)
    parser.add_argument("--neighbors", type=int, default=20)
    parser.add_argument("--dimensions", type=int, default=15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--top-terms", type=int, default=15)
    parser.add_argument("--include-title-only", action="store_true")
    parser.add_argument("--limit", type=int, help="Use only the first N documents for testing")
    args = parser.parse_args()
    seed_everything(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(Path("data/model_cache").resolve()))

    frame = load_documents(args.input, require_abstract=not args.include_title_only)
    if args.limit:
        frame = frame.head(args.limit).copy()
    if len(frame) < args.min_cluster_size * 2:
        raise SystemExit("Not enough documents for clustering")
    device = device_name(args.device)
    print(f"documents={len(frame)} device={device}", flush=True)
    embeddings = specter2_embeddings(frame["document_text"].tolist(), args.model, args.adapter,
                                      args.batch_size, device, args.max_length)
    np.save(args.output_dir / "embeddings.npy", embeddings)

    reducer = umap.UMAP(n_neighbors=args.neighbors, n_components=args.dimensions,
                        min_dist=0.0, metric="cosine", random_state=args.seed)
    reduced = reducer.fit_transform(embeddings)
    clusterer = hdbscan.HDBSCAN(min_cluster_size=args.min_cluster_size,
                                min_samples=args.min_samples, metric="euclidean",
                                cluster_selection_method="eom", prediction_data=True)
    labels = clusterer.fit_predict(reduced)
    probabilities = clusterer.probabilities_

    visual = umap.UMAP(n_neighbors=args.neighbors, n_components=2, min_dist=0.08,
                       metric="cosine", random_state=args.seed).fit_transform(embeddings)
    np.save(args.output_dir / "coordinates_2d.npy", visual)
    terms = topic_terms(frame["document_text"].tolist(), labels, args.top_terms)

    frame["topic_id"] = labels
    frame["topic_probability"] = probabilities
    frame["x"] = visual[:, 0]
    frame["y"] = visual[:, 1]
    assignment_fields = ["record_id", "source_record_ids", "duplicate_record_count", "report_year",
                         "original_title", "canonical_title", "doi",
                         "authors", "input_quality", "topic_id", "topic_probability", "x", "y"]
    frame[assignment_fields].to_csv(args.output_dir / "article_topic_assignments.csv", index=False)

    topics = []
    for topic in sorted(terms):
        indices = np.where(labels == topic)[0]
        centroid = reduced[indices].mean(axis=0)
        representative = indices[np.argsort(np.linalg.norm(reduced[indices] - centroid, axis=1))[:5]]
        topics.append({
            "topic_id": topic,
            "size": int(len(indices)),
            "top_terms": [term for term, _ in terms[topic]],
            "representative_titles": frame.iloc[representative]["canonical_title"].tolist(),
        })
    (args.output_dir / "topics.json").write_text(json.dumps(topics, indent=2), encoding="utf-8")
    with (args.output_dir / "topics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["topic_id", "size", "top_terms", "representative_titles"])
        writer.writeheader()
        for topic in topics:
            writer.writerow({**topic, "top_terms": "; ".join(topic["top_terms"]),
                             "representative_titles": " | ".join(topic["representative_titles"])})

    clustered = labels >= 0
    metrics = {
        "model": args.model, "adapter": args.adapter, "device": device,
        "documents": int(len(frame)),
        "source_records": int(frame["duplicate_record_count"].sum()),
        "duplicate_source_records_removed": int(frame["duplicate_record_count"].sum() - len(frame)),
        "embedding_dimensions": int(embeddings.shape[1]),
        "topics": len(topics), "noise_documents": int((labels < 0).sum()),
        "noise_fraction": round(float((labels < 0).mean()), 4),
        "cluster_sizes": dict(sorted(Counter(labels[clustered].tolist()).items())),
        "silhouette_reduced": (round(float(silhouette_score(reduced[clustered], labels[clustered])), 4)
                               if len(set(labels[clustered])) > 1 else None),
        "parameters": vars(args) | {"input": str(args.input), "output_dir": str(args.output_dir)},
    }
    (args.output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    print(json.dumps({key: value for key, value in metrics.items() if key not in {"cluster_sizes", "parameters"}}, indent=2))


if __name__ == "__main__":
    main()
