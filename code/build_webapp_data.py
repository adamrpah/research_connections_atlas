#!/usr/bin/env python3
"""Build validated, app-ready scholarly-impact datasets.

This stage does not alter or review topic assignments. It packages the analytical
outputs into stable entities, graph edges, search artifacts, provenance, and a
feedback contract. Coauthor edges are reserved for the later author-resolution stage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCHEMA_VERSION = "1.0.0"


def text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def scalar(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def stable_id(prefix: str, key: str, length: int = 16) -> str:
    digest = hashlib.sha256(key.casefold().strip().encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def publication_id(doi: Any, title: Any) -> str:
    key = f"doi:{text(doi).lower()}" if text(doi) else f"title:{normalize_title(text(title))}"
    return stable_id("pub", key)


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def split_semicolon(value: Any) -> list[str]:
    return [part.strip() for part in text(value).split(";") if part.strip()]


def split_pipe(value: Any) -> list[str]:
    return [part.strip() for part in text(value).split("|") if part.strip()]


def parse_json_list(value: Any) -> list[dict]:
    if not text(value):
        return []
    try:
        parsed = json.loads(text(value))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def unique(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value not in (None, "")))


def dump_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cosine_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=Path("results/publication_candidates.csv"))
    parser.add_argument("--resolution", type=Path, default=Path("results/publication_resolution/publication_resolution.csv"))
    parser.add_argument("--topic-dir", type=Path, default=Path("results/topic_model_specter2"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/webapp"))
    parser.add_argument("--similarity-neighbors", type=int, default=10)
    parser.add_argument("--min-similarity", type=float, default=0.35)
    parser.add_argument("--recency-half-life", type=float, default=5.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    candidates = pd.read_csv(args.candidates, dtype={"record_id": str}).fillna("")
    resolution = pd.read_csv(args.resolution, dtype={"record_id": str}).fillna("")
    articles = pd.read_csv(args.topic_dir / "labeled_article_topics.csv", dtype={"record_id": str}).fillna("")
    topic_frame = pd.read_csv(args.topic_dir / "labeled_topics.csv").fillna("")
    faculty_works = pd.read_csv(args.topic_dir / "faculty_topic_publications.csv", dtype={"record_id": str}).fillna("")
    embeddings = np.load(args.topic_dir / "embeddings.npy")
    if len(articles) != len(embeddings):
        raise ValueError("Article assignments and embedding rows are not aligned")

    candidate_by_id = candidates.set_index("record_id", drop=False).to_dict(orient="index")
    resolution_by_id = resolution.set_index("record_id", drop=False).to_dict(orient="index")
    article_index = {row.record_id: index for index, row in articles.iterrows()}

    # Stable faculty registry. Publication attribution is already restricted to
    # OpenAlex author metadata by resolve_faculty_attributions.py.
    faculty_names = sorted(faculty_works["faculty_name"].unique(), key=str.casefold)
    faculty_ids = {name: stable_id("faculty", name) for name in faculty_names}
    aliases: dict[str, set[str]] = {name: {name} for name in faculty_names}
    faculty_source_years: dict[str, list[int]] = {name: [] for name in faculty_names}
    for row in faculty_works.to_dict(orient="records"):
        name = row["faculty_name"]
        for source_id in split_semicolon(row["source_record_ids"]):
            candidate = candidate_by_id.get(source_id, {})
            year = candidate.get("report_year")
            if text(year):
                faculty_source_years[name].append(int(float(year)))

    faculties = []
    for name in faculty_names:
        years = faculty_source_years[name]
        faculties.append({
            "id": faculty_ids[name], "feedback_target_id": faculty_ids[name],
            "display_name": name, "aliases": sorted(aliases[name], key=str.casefold),
            "first_report_year": min(years) if years else None,
            "last_report_year": max(years) if years else None,
            "role_status": "faculty_or_report_attributed_researcher",
        })

    # Topic registry includes an explicit unclustered entity so every publication
    # has a valid topic target and can receive topic-quality feedback.
    topics = []
    topic_ids: dict[int, str] = {-1: "topic_unclustered"}
    for row in topic_frame.sort_values("topic_id").to_dict(orient="records"):
        number = int(row["topic_id"])
        topic_ids[number] = f"topic_{number:02d}"
        topics.append({
            "id": topic_ids[number], "feedback_target_id": topic_ids[number],
            "model_topic_id": number, "label": text(row["topic_label"]),
            "description": text(row["topic_description"]), "publication_count": int(row["size"]),
            "top_terms": split_semicolon(row["top_terms"]),
            "representative_titles": split_pipe(row["representative_titles"]),
        })
    unclustered_count = int((articles["topic_id"].astype(int) == -1).sum())
    topics.append({
        "id": "topic_unclustered", "feedback_target_id": "topic_unclustered",
        "model_topic_id": -1, "label": "Unclustered / Cross-Cutting Research",
        "description": "Research not assigned to a sufficiently dense topic cluster; these works may be interdisciplinary, niche, or underrepresented.",
        "publication_count": unclustered_count, "top_terms": [], "representative_titles": [],
    })

    faculty_for_article: dict[str, list[str]] = {}
    for row in faculty_works.to_dict(orient="records"):
        faculty_for_article.setdefault(row["record_id"], []).append(row["faculty_name"])

    publications = []
    pub_ids: dict[str, str] = {}
    pub_years: dict[str, int | None] = {}
    search_documents = []
    provenance_records = []
    for row in articles.to_dict(orient="records"):
        source_ids = split_semicolon(row["source_record_ids"])
        resolved = [resolution_by_id[x] for x in source_ids if x in resolution_by_id]
        resolved.sort(key=lambda item: len(text(item.get("abstract"))), reverse=True)
        best = resolved[0] if resolved else {}
        canonical_title = text(row["canonical_title"]) or text(row["original_title"])
        doi = text(row["doi"]) or text(best.get("doi"))
        pid = publication_id(doi, canonical_title)
        if pid in pub_ids.values():
            raise ValueError(f"Stable publication ID collision for {canonical_title}")
        pub_ids[row["record_id"]] = pid
        year_value = best.get("publication_year") or row.get("report_year")
        year = int(float(year_value)) if text(year_value) else None
        pub_years[row["record_id"]] = year
        names = sorted(unique(faculty_for_article.get(row["record_id"], [])), key=str.casefold)
        authors = unique(split_semicolon(best.get("authors")) + split_semicolon(row.get("authors")))
        candidate_rows = [candidate_by_id[x] for x in source_ids if x in candidate_by_id]
        provenance = []
        for source in candidate_rows:
            item = {
                "source_record_id": source["record_id"],
                "report_year": int(float(source["report_year"])) if text(source["report_year"]) else None,
                "report_file": text(source["report_file"]),
                "pdf_page": int(float(source["pdf_page"])) if text(source["pdf_page"]) else None,
                "raw_citation": text(source["raw_citation"]),
                "extraction_confidence": float(source["confidence"]) if text(source["confidence"]) else None,
                "needs_review": str(source["needs_review"]).casefold() == "true",
                "resolution_match_score": float(resolution_by_id.get(source["record_id"], {}).get("match_score")) if text(resolution_by_id.get(source["record_id"], {}).get("match_score")) else None,
            }
            provenance.append(item)
            provenance_records.append({"publication_id": pid, **item})
        topic_number = int(row["topic_id"])
        publication = {
            "id": pid, "feedback_target_id": pid, "title": canonical_title,
            "publication_year": year, "doi": doi or None,
            "landing_url": text(best.get("landing_url")) or None,
            "pdf_url": text(best.get("pdf_url")) or None,
            "local_pdf": text(best.get("local_pdf")) or None,
            "abstract": text(best.get("abstract")) or None,
            "local_abstract": text(best.get("local_abstract")) or None,
            "authors": authors,
            "openalex_work_id": text(best.get("openalex_work_id")) or None,
            "openalex_authorships": parse_json_list(best.get("openalex_authorships")),
            "faculty_ids": [faculty_ids[name] for name in names],
            "topic_id": topic_ids[topic_number], "model_topic_id": topic_number,
            "topic_probability": float(row["topic_probability"]),
            "input_quality": text(row["input_quality"]),
            "coordinates": {"x": float(row["x"]), "y": float(row["y"])},
            "source_record_ids": source_ids, "provenance": provenance,
            "quality": {
                "has_abstract": bool(text(best.get("abstract"))),
                "has_pdf": bool(text(best.get("local_pdf"))),
                "match_source": text(best.get("match_source")) or None,
                "match_score": float(best["match_score"]) if text(best.get("match_score")) else None,
            },
        }
        publications.append(publication)
        search_documents.append({
            "id": f"search_{pid}", "entity_type": "publication", "entity_id": pid,
            "title": canonical_title, "text": " ".join(filter(None, [canonical_title, text(best.get("abstract")), " ".join(authors)])),
            "topic_ids": [topic_ids[topic_number]], "faculty_ids": publication["faculty_ids"],
        })

    # Weighted faculty-topic edges and publication membership edges.
    max_year = max(year for year in pub_years.values() if year is not None)
    faculty_topic_edges = []
    publication_faculty_edges = []
    attribution_lookup = {
        (row["record_id"], row["faculty_name"]): row
        for row in faculty_works.to_dict(orient="records")
    }
    record_by_publication_id = {value: key for key, value in pub_ids.items()}
    faculty_name_by_id = {value: key for key, value in faculty_ids.items()}
    for publication in publications:
        for fid in publication["faculty_ids"]:
            faculty_name = faculty_name_by_id[fid]
            attribution = attribution_lookup[(record_by_publication_id[publication["id"]], faculty_name)]
            eid = stable_id("edge", f"publication_faculty:{publication['id']}:{fid}")
            publication_faculty_edges.append({
                "id": eid, "feedback_target_id": eid, "source": fid,
                "target": publication["id"], "type": "attributed_publication",
                "attribution_basis": text(attribution.get("attribution_basis")) or "openalex_author_metadata",
                "attribution_confidence": scalar(attribution.get("attribution_confidence")),
                "attribution_evidence": text(attribution.get("attribution_evidence")) or None,
            })
    clustered_fw = faculty_works[faculty_works["topic_id"].astype(int) >= 0].copy()
    for (name, topic_number), group in clustered_fw.groupby(["faculty_name", "topic_id"]):
        topic_number = int(topic_number)
        article_ids = unique(group["record_id"].tolist())
        years = [pub_years[x] for x in article_ids if pub_years.get(x) is not None]
        recency = sum(0.5 ** ((max_year - year) / args.recency_half_life) for year in years)
        all_for_faculty = clustered_fw[clustered_fw["faculty_name"] == name]["record_id"].nunique()
        fid, tid = faculty_ids[name], topic_ids[topic_number]
        eid = stable_id("edge", f"faculty_topic:{fid}:{tid}")
        faculty_topic_edges.append({
            "id": eid, "feedback_target_id": eid, "source": fid, "target": tid,
            "type": "faculty_topic", "publication_count": len(article_ids),
            "share_of_faculty_clustered_publications": round(len(article_ids) / all_for_faculty, 6),
            "mean_topic_probability": round(float(group["topic_probability"].mean()), 6),
            "recency_weighted_publication_count": round(recency, 6),
            "first_publication_year": min(years) if years else None,
            "last_publication_year": max(years) if years else None,
            "publication_ids": [pub_ids[x] for x in article_ids],
        })

    # Faculty profiles and research-similarity edges use both topic distributions
    # and mean SPECTER2 embeddings. This expresses potential overlap, not authorship.
    faculty_vectors = []
    topic_vectors = []
    topic_columns = sorted(number for number in topic_ids if number >= 0)
    faculty_profiles = []
    for name in faculty_names:
        work_ids = unique(faculty_works.loc[faculty_works["faculty_name"] == name, "record_id"].tolist())
        indices = [article_index[x] for x in work_ids]
        faculty_vectors.append(embeddings[indices].mean(axis=0))
        counts = faculty_works[(faculty_works["faculty_name"] == name) & (faculty_works["topic_id"].astype(int) >= 0)].groupby("topic_id")["record_id"].nunique()
        vector = np.array([float(counts.get(number, 0)) for number in topic_columns])
        topic_vectors.append(vector / max(vector.sum(), 1.0))
        edges = sorted((edge for edge in faculty_topic_edges if edge["source"] == faculty_ids[name]), key=lambda edge: (-edge["publication_count"], edge["target"]))
        faculty_profiles.append({
            "faculty_id": faculty_ids[name], "display_name": name,
            "publication_count": len(work_ids), "topic_count": len(edges),
            "topics": [{key: edge[key] for key in ("target", "publication_count", "share_of_faculty_clustered_publications", "mean_topic_probability", "recency_weighted_publication_count")} for edge in edges],
        })
        search_documents.append({
            "id": f"search_{faculty_ids[name]}", "entity_type": "faculty", "entity_id": faculty_ids[name],
            "title": name, "text": " ".join([name] + sorted(aliases[name]) + [next(topic["label"] for topic in topics if topic["id"] == edge["target"]) for edge in edges]),
            "topic_ids": [edge["target"] for edge in edges], "faculty_ids": [faculty_ids[name]],
        })
    faculty_vectors = cosine_rows(np.vstack(faculty_vectors))
    topic_vectors = cosine_rows(np.vstack(topic_vectors))
    faculty_similarity_edges = []
    for left in range(len(faculty_names)):
        candidates_for_left = []
        for right in range(left + 1, len(faculty_names)):
            embedding_similarity = float(faculty_vectors[left] @ faculty_vectors[right])
            topic_similarity = float(topic_vectors[left] @ topic_vectors[right])
            combined = 0.6 * embedding_similarity + 0.4 * topic_similarity
            if combined >= args.min_similarity:
                candidates_for_left.append((combined, right, embedding_similarity, topic_similarity))
        for combined, right, embedding_similarity, topic_similarity in sorted(candidates_for_left, reverse=True)[:args.similarity_neighbors]:
            left_name, right_name = faculty_names[left], faculty_names[right]
            left_topics = set(faculty_works[(faculty_works["faculty_name"] == left_name) & (faculty_works["topic_id"].astype(int) >= 0)]["topic_id"].astype(int))
            right_topics = set(faculty_works[(faculty_works["faculty_name"] == right_name) & (faculty_works["topic_id"].astype(int) >= 0)]["topic_id"].astype(int))
            shared = sorted(left_topics & right_topics)
            source, target = faculty_ids[left_name], faculty_ids[right_name]
            eid = stable_id("edge", f"faculty_similarity:{source}:{target}")
            faculty_similarity_edges.append({
                "id": eid, "feedback_target_id": eid, "source": source, "target": target,
                "type": "research_similarity", "combined_similarity": round(combined, 6),
                "embedding_similarity": round(embedding_similarity, 6),
                "topic_profile_similarity": round(topic_similarity, 6),
                "shared_topic_ids": [topic_ids[number] for number in shared],
                "explanation": "Shared research themes: " + ", ".join(next(topic["label"] for topic in topics if topic["id"] == topic_ids[number]) for number in shared) if shared else "Similar publication-text embeddings",
            })

    # Search embedding rows align exactly with semantic_search_index.json. Faculty
    # documents use their mean article vector; topic documents use mean member vectors.
    semantic_rows, semantic_index = [], []
    for row_index, publication in enumerate(publications):
        semantic_rows.append(embeddings[row_index])
        semantic_index.append({"row": len(semantic_rows) - 1, "entity_type": "publication", "entity_id": publication["id"]})
    for index, name in enumerate(faculty_names):
        semantic_rows.append(faculty_vectors[index])
        semantic_index.append({"row": len(semantic_rows) - 1, "entity_type": "faculty", "entity_id": faculty_ids[name]})
    semantic_topic_numbers = topic_columns + [-1]
    for number in semantic_topic_numbers:
        indices = np.where(articles["topic_id"].astype(int).to_numpy() == number)[0]
        semantic_rows.append(embeddings[indices].mean(axis=0))
        semantic_index.append({"row": len(semantic_rows) - 1, "entity_type": "topic", "entity_id": topic_ids[number]})
        topic = next(item for item in topics if item["id"] == topic_ids[number])
        search_documents.append({
            "id": f"search_{topic_ids[number]}", "entity_type": "topic", "entity_id": topic_ids[number],
            "title": topic["label"], "text": " ".join([topic["label"], topic["description"], *topic["top_terms"]]),
            "topic_ids": [topic_ids[number]], "faculty_ids": [],
        })
    np.save(args.output_dir / "semantic_search_embeddings.npy", cosine_rows(np.vstack(semantic_rows)).astype(np.float32))

    nodes = ([{"id": item["id"], "type": "faculty", "label": item["display_name"]} for item in faculties]
             + [{"id": item["id"], "type": "topic", "label": item["label"]} for item in topics]
             + [{"id": item["id"], "type": "publication", "label": item["title"]} for item in publications])
    coauthor_edges: list[dict] = []
    graph_edges = publication_faculty_edges + faculty_topic_edges + faculty_similarity_edges + coauthor_edges

    feedback_config = {
        "schema_version": "1.0.0",
        "target_types": ["faculty", "publication", "topic", "edge"],
        "feedback_types": {
            "topic_quality": ["incorrect_topic", "topic_too_broad", "topic_too_narrow", "unclear_label", "incorrect_description", "suggested_topic"],
            "attribution_error": ["wrong_faculty", "missing_faculty", "duplicate_faculty", "name_error", "wrong_publication"],
            "metadata_error": ["title", "year", "doi", "authors", "abstract", "url"],
        },
        "submission_fields": {
            "required": ["target_type", "target_id", "feedback_category", "feedback_type", "comment"],
            "optional": ["suggested_value", "contact_email", "page_url", "dataset_version"],
        },
        "note": "The static dataset defines valid targets and payload fields. The web app still needs a writable API or form backend to store submissions.",
    }

    outputs = {
        "faculty.json": faculties, "topics.json": topics, "publications.json": publications,
        "faculty_profiles.json": faculty_profiles, "publication_provenance.json": provenance_records,
        "graph_nodes.json": nodes, "graph_edges.json": graph_edges,
        "faculty_topic_edges.json": faculty_topic_edges,
        "faculty_similarity_edges.json": faculty_similarity_edges,
        "publication_faculty_edges.json": publication_faculty_edges,
        "coauthor_edges.json": coauthor_edges, "search_documents.json": search_documents,
        "semantic_search_index.json": semantic_index, "feedback_config.json": feedback_config,
    }
    for filename, payload in outputs.items():
        dump_json(args.output_dir / filename, payload)

    # Referential, numeric, and serialization validation.
    node_ids = [node["id"] for node in nodes]
    edge_ids = [edge["id"] for edge in graph_edges]
    checks = {
        "unique_node_ids": len(node_ids) == len(set(node_ids)),
        "unique_edge_ids": len(edge_ids) == len(set(edge_ids)),
        "no_dangling_edges": all(edge["source"] in set(node_ids) and edge["target"] in set(node_ids) for edge in graph_edges),
        "all_publications_have_topics": all(item["topic_id"] in set(topic_ids.values()) for item in publications),
        "all_topics_described": all(item["label"] and item["description"] for item in topics),
        "semantic_index_aligned": len(semantic_index) == len(semantic_rows),
        "local_paths_valid": all((not item["local_pdf"] or Path(item["local_pdf"]).exists()) and (not item["local_abstract"] or Path(item["local_abstract"]).exists()) for item in publications),
        "publication_count_reconciles": len(publications) == len(articles),
    }
    if not all(checks.values()):
        raise ValueError(f"Web-app dataset validation failed: {checks}")

    manifest_path = args.output_dir / "manifest.json"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_model_metrics": json.loads((args.topic_dir / "metrics.json").read_text(encoding="utf-8")),
        "parameters": {
            "similarity_neighbors": args.similarity_neighbors,
            "min_similarity": args.min_similarity,
            "recency_half_life_years": args.recency_half_life,
            "recency_reference_year": max_year,
        },
        "counts": {
            "faculty": len(faculties), "topics": len(topics), "publications": len(publications),
            "graph_nodes": len(nodes), "graph_edges": len(graph_edges),
            "faculty_topic_edges": len(faculty_topic_edges),
            "faculty_similarity_edges": len(faculty_similarity_edges),
            "publication_faculty_edges": len(publication_faculty_edges),
            "coauthor_edges": 0, "search_documents": len(search_documents),
        },
        "validation": checks,
        "coauthor_status": "pending_author_identity_resolution",
        "feedback_status": "targets_and_submission_contract_ready; writable submission backend not included",
        "files": {},
    }
    for path in sorted(args.output_dir.iterdir()):
        if path.is_file() and path.name != manifest_path.name:
            manifest["files"][path.name] = {"bytes": path.stat().st_size, "sha256": checksum(path)}
    dump_json(manifest_path, manifest)
    print(json.dumps({"counts": manifest["counts"], "validation": checks}, indent=2))


if __name__ == "__main__":
    main()
