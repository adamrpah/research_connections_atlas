"""Small SPECTER2 HTTP service for the Research Connections Atlas.

Run from the repository root after installing topic_model_requirements.txt:
    python code/serve_specter2_matcher.py
"""
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import torch
from adapters import AutoAdapterModel
from transformers import AutoTokenizer


class Matcher:
    def __init__(self, embeddings_path: Path, index_path: Path, model_name: str, adapter_name: str):
        self.embeddings = np.load(embeddings_path).astype(np.float32)
        self.index = json.loads(index_path.read_text())
        if len(self.index) != len(self.embeddings):
            raise ValueError("Semantic index and embedding rows do not align")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoAdapterModel.from_pretrained(model_name)
        loaded = self.model.load_adapter(adapter_name, source="hf", set_active=False)
        self.model.set_active_adapters(loaded)
        self.model.eval()
        self.model_name = f"{model_name} + {adapter_name} proximity adapter"

    def match(self, abstract: str, limit: int = 5) -> dict:
        text = f"Title: Untitled manuscript\nAbstract: {abstract}"
        tokens = self.tokenizer(text, truncation=True, max_length=512, return_tensors="pt")
        with torch.inference_mode():
            vector = self.model(**tokens).last_hidden_state[:, 0, :]
            vector = torch.nn.functional.normalize(vector, p=2, dim=1).cpu().numpy()[0]
        scores = self.embeddings @ vector

        def best(entity_type: str):
            rows = [(float(scores[item["row"]]), item["entity_id"]) for item in self.index if item["entity_type"] == entity_type]
            return [{"id": entity_id, "score": round(score, 6)} for score, entity_id in sorted(rows, reverse=True)[:limit]]

        return {"topics": best("topic"), "faculty": best("faculty"), "model": self.model_name}


def handler_for(matcher: Matcher, token: str | None):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/match":
                return self.respond(404, {"error": "Not found"})
            if token and self.headers.get("authorization") != f"Bearer {token}":
                return self.respond(401, {"error": "Unauthorized"})
            try:
                length = min(int(self.headers.get("content-length", "0")), 20_000)
                payload = json.loads(self.rfile.read(length))
                abstract = str(payload.get("abstract", "")).strip()[:6000]
                if len(abstract) < 80:
                    return self.respond(400, {"error": "Abstract must be at least 80 characters"})
                self.respond(200, matcher.match(abstract))
            except Exception as error:
                print(f"match failed: {error}", flush=True)
                self.respond(500, {"error": "Matching failed"})

        def respond(self, status: int, payload: dict):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            print(format % args, flush=True)

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--embeddings", type=Path, default=Path("results/webapp/semantic_search_embeddings.npy"))
    parser.add_argument("--index", type=Path, default=Path("results/webapp/semantic_search_index.json"))
    parser.add_argument("--model", default="allenai/specter2_base")
    parser.add_argument("--adapter", default="allenai/specter2")
    args = parser.parse_args()
    matcher = Matcher(args.embeddings, args.index, args.model, args.adapter)
    server = ThreadingHTTPServer((args.host, args.port), handler_for(matcher, os.getenv("SPECTER2_API_TOKEN")))
    print(f"SPECTER2 matcher listening on http://{args.host}:{args.port}/match", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
