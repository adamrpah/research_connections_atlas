---
title: Research Atlas SPECTER2 Matcher
emoji: 🧭
colorFrom: green
colorTo: yellow
sdk: gradio
sdk_version: 5.49.1
app_file: app.py
python_version: 3.10.13
pinned: false
license: apache-2.0
preload_from_hub:
  - allenai/specter2_base
  - allenai/specter2
---

# Research Atlas SPECTER2 Matcher

Proof-of-concept semantic matching service for the Research Connections Atlas.
It embeds a submitted abstract using the SPECTER2 base model with the proximity
adapter and compares that vector with precomputed topic and faculty profiles.

Abstracts are processed in memory and are not stored by the application.

