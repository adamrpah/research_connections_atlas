from __future__ import annotations

import json
from pathlib import Path

import gradio as gr
import numpy as np
import spaces
import torch
from adapters import AutoAdapterModel
from transformers import AutoTokenizer


MODEL_NAME = "allenai/specter2_base"
ADAPTER_NAME = "allenai/specter2"
DATA_DIR = Path(__file__).parent / "data"

embeddings = np.load(DATA_DIR / "semantic_search_embeddings.npy").astype(np.float32)
semantic_index = json.loads((DATA_DIR / "semantic_search_index.json").read_text())
if len(semantic_index) != len(embeddings):
    raise RuntimeError("Semantic index and embedding rows do not align")

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoAdapterModel.from_pretrained(MODEL_NAME)
loaded_adapter = model.load_adapter(ADAPTER_NAME, source="hf", set_active=False)
model.set_active_adapters(loaded_adapter)
if not model.active_adapters:
    raise RuntimeError("SPECTER2 proximity adapter failed to activate")
model.eval()
model.to("cuda")


def ranked_matches(scores: np.ndarray, entity_type: str, limit: int = 5) -> list[dict]:
    candidates = [
        (float(scores[item["row"]]), item["entity_id"])
        for item in semantic_index
        if item["entity_type"] == entity_type
    ]
    return [
        {"id": entity_id, "score": round(score, 6)}
        for score, entity_id in sorted(candidates, reverse=True)[:limit]
    ]


@spaces.GPU(duration=20)
def match_abstract(abstract: str) -> dict:
    abstract = (abstract or "").strip()[:6000]
    if len(abstract) < 80:
        raise gr.Error("Please enter a fuller abstract (at least 80 characters).")

    document = f"Title: Untitled manuscript\nAbstract: {abstract}"
    tokens = tokenizer(
        document,
        truncation=True,
        max_length=512,
        return_tensors="pt",
        return_token_type_ids=False,
    )
    tokens = {name: value.to("cuda") for name, value in tokens.items()}
    with torch.inference_mode():
        vector = model(**tokens).last_hidden_state[:, 0, :]
        vector = torch.nn.functional.normalize(vector, p=2, dim=1)
        query = vector.detach().cpu().float().numpy()[0]
    scores = embeddings @ query
    return {
        "topics": ranked_matches(scores, "topic"),
        "faculty": ranked_matches(scores, "faculty"),
        "model": f"{MODEL_NAME} + {ADAPTER_NAME} proximity adapter",
    }


with gr.Blocks(title="Research Atlas SPECTER2 Matcher") as demo:
    gr.Markdown(
        "# Research Atlas SPECTER2 Matcher\n"
        "Paste a scholarly abstract to find the closest research themes and faculty "
        "profiles in the Research Connections Atlas. Abstracts are not stored."
    )
    abstract_input = gr.Textbox(
        label="Research abstract",
        placeholder="Paste an abstract of at least 80 characters…",
        lines=10,
        max_lines=18,
    )
    match_button = gr.Button("Find connections", variant="primary")
    result_output = gr.JSON(label="Closest atlas connections")
    match_button.click(
        match_abstract,
        inputs=abstract_input,
        outputs=result_output,
        api_name="match",
        concurrency_limit=1,
    )


if __name__ == "__main__":
    demo.launch()
