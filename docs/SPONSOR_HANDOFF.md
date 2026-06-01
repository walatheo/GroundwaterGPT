# EAGLE / GroundwaterGPT — Sponsor / Operator Handoff

This page is the single entry point for a new operator (sponsor, advisor, or successor researcher) to run EAGLE from a fresh clone. For the next **engineering maintainer**, also read the root [HANDOFF.md](../HANDOFF.md) — it covers fragility, latency caveats, and the recommended order of next-team work.

## 1. What you are receiving

EAGLE is a deterministic Florida USGS groundwater research platform with an evidence-bound language layer. The reproducible claims live in the deterministic pipeline; the LLM only narrates. The primary references are:

| Doc | Purpose |
|-----|---------|
| [README.md](../README.md) | Top-level quick start and project map |
| [HANDOFF.md (root)](../HANDOFF.md) | Engineering-successor handoff: what works, known fragility, next-team priorities |
| [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) | Recommended 5-minute demo arc and backup paths |
| [EAGLE_TECHNICAL_OVERVIEW.md](EAGLE_TECHNICAL_OVERVIEW.md) | Audit-oriented system description |
| [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) | Architecture and developer workflow |
| [ENGINEERING_STANDARDS.md](ENGINEERING_STANDARDS.md) | Testing, code quality, and review standards |

## 2. Prerequisites

- Python 3.10 or newer (`python3 --version`)
- Node 18 or newer (`node --version`)
- `curl`, `jq`, `make`, `lsof` (standard on macOS / Linux)
- Optional, for the LLM narration path: [Ollama](https://ollama.com) with `qwen3:8b` pulled locally

The demo will refuse to start if the Python or Node versions are too low — see [scripts/start_demo.sh](../scripts/start_demo.sh).

## 3. First-run setup

```bash
git clone https://github.com/walatheo/GroundwaterGPT.git
cd GroundwaterGPT

# Python deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Note: requirements-lite.txt pins pandas==2.1.3 / numpy==1.24.3, which lack
# Python 3.13 wheels. Use the unpinned requirements.txt on 3.13, or pin your
# interpreter to 3.10–3.12 if you need the reproducible lite set.

# Frontend deps
cd frontend && npm install && cd ..

# Environment (LLM is optional for the deterministic demo)
cp .env.example .env
# Edit .env if you intend to use the hosted Qwen / DashScope path.
```

### Data

The `data/` directory is intentionally gitignored — local USGS CSVs and ChromaDB stores are regenerated, not version-controlled. You have two options:

- **Receive a snapshot** (preferred for handoff). Drop the provided `data/` archive in the repo root and unzip; you should end up with ~40 `usgs_*.csv` files plus a `pipeline_manifest_*.json`.
- **Regenerate from USGS NWIS.** Run `python -m src.data.download_data` to fetch the canonical Florida sites listed in [config/config.py](../config/config.py). This hits the public USGS NWIS API and takes a few minutes.

Without `data/`, the deterministic API returns 200 on `/api/chat/status` but every cohort query degrades to "No time series available for this query." Don't skip this step before a demo.

## 4. Running the demo

```bash
make demo
```

`make demo` runs [scripts/start_demo.sh](../scripts/start_demo.sh), which:

1. Verifies Python 3.10+ and Node 18+.
2. Frees any stale process on ports 8000 and 3000.
3. Starts FastAPI on `:8000` with `GROUNDWATERGPT_SKIP_AGENT_INIT=1`.
4. Waits up to 20 s for `/api/chat/status` to return 200.
5. Starts Vite on `:3000`.
6. Tails `/tmp/gwgpt-backend.log` and `/tmp/gwgpt-frontend.log`.

When the script prints `Demo ready: http://localhost:3000`, open the URL. Smoke-test prompts (also in [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md)):

- `Estero trends` — 10-well cohort chart.
- `compare G-3336 and G-5004` — 2-well overlay.
- `which aquifer supplies Estero?` — text-only answer, no chart.

To stop the demo, press `Ctrl+C` in the terminal that is running `make demo`. Both servers shut down via the trap in `start_demo.sh`.

## 5. Verifying the deterministic guarantee

The manuscript claim rests on this benchmark, not on chat quality:

```bash
make benchmark
jq '.summary' chat_benchmark_report.json
```

Expected: 68/68 cases pass with overall score 1.000, citation coverage 1.000, and claim-verdict coverage 1.000. Re-run any time you suspect drift.

## 6. Optional: LLM narration path

The default `make demo` runs deterministic-only (no LLM). To enable Qwen-backed narration:

```bash
# Local Ollama (no API key required)
ollama serve
ollama pull qwen3:8b

# In another terminal, start the API without the skip flag:
LLM_PROVIDER=ollama LLM_MODEL=qwen3:8b uvicorn api.main:app --port 8000
```

Hosted DashScope is also supported by setting `LLM_PROVIDER=qwen` and `DASHSCOPE_API_KEY` in `.env`. **Do not commit `.env`.** Qwen is the only supported provider; legacy Gemini / Anthropic / OpenAI fallbacks have been removed.

## 7. Known limitations

- Live LLM-synthesis latency is not production-ready; first-call cold start can exceed per-request budgets.
- Risk labels and changepoints are screening heuristics, not statistically calibrated regime shifts. See "Things Not To Claim" in [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) §8.
- Scope is Florida monitoring sites only.
- `outputs/`, `knowledge_base/`, `chroma_db/`, and `data/` are gitignored — treat them as regenerable.

## 8. Fresh-clone verification — last run

Verified 2026-05-31 from a clean worktree at commit `3a2ea56` on macOS / Python 3.13.7 / Node 25.5.0:

- `pip install -r requirements.txt` — installs cleanly.
- `pip install -r requirements-lite.txt` — fails on Python 3.13 (pandas wheel gap, noted above).
- `cd frontend && npm install` — installs cleanly.
- `GROUNDWATERGPT_SKIP_AGENT_INIT=1 uvicorn api.main:app` — `/api/chat/status` returns 200 within 8 s.
- `make demo` preflight — Python and Node checks pass.

## 9. Where to ask questions

- Repo: https://github.com/walatheo/GroundwaterGPT
- Maintainer: walatheo (see `git log` for contact)
- Issues: open a GitHub issue with the failing command, the relevant log tail, and your Python / Node versions.
