# GroundwaterGPT Demo Runbook

**Last Updated:** February 28, 2026

## 1. Demo Goals

Use this runbook to demo:
1. System health and fallback readiness
2. Deep research response with claim citations
3. End-to-end research workflow (plan -> run -> draft)
4. Benchmark harness execution and score report

## 2. Quick Prerequisites

```bash
cd /Users/salatheoclay/Desktop/GroundwaterGPT/GroundwaterGPT
source .venv/bin/activate  # if available
export GROUNDWATERGPT_SKIP_AGENT_INIT=1
```

`GROUNDWATERGPT_SKIP_AGENT_INIT=1` keeps the demo deterministic and avoids external LLM startup dependencies.

## 3. API Demo (Terminal)

### Terminal A - Start API

```bash
cd /Users/salatheoclay/Desktop/GroundwaterGPT/GroundwaterGPT
export GROUNDWATERGPT_SKIP_AGENT_INIT=1
uvicorn api.main:app --reload --port 8000
```

### Terminal B - Run demo calls

#### 3.1 Health check

```bash
curl -s http://127.0.0.1:8000/api/chat/status | jq
```

#### 3.2 Deep research with citations (Estero benchmark)

```bash
curl -s http://127.0.0.1:8000/api/research \
  -H 'Content-Type: application/json' \
  -d '{"question":"What has been the change in groundwater level in Estero over the last 30 years?"}' | jq
```

Expected highlights:
- `report`
- `claim_citations[]`
- `citation_summary.citation_coverage`
- `sources` includes USGS monitoring-location URLs

#### 3.3 Create plan

```bash
curl -s http://127.0.0.1:8000/api/research/plans \
  -H 'Content-Type: application/json' \
  -d '{
    "title":"Estero Groundwater Benchmark",
    "research_question":"How have Estero groundwater levels changed?",
    "hypothesis":"Groundwater shows measurable long-term trend.",
    "methodology":"Analyze available USGS time series and summarize trend metrics.",
    "datasets":["USGS Water Data"],
    "metrics":["net_change_ft","annual_change_ft_per_year"],
    "baselines":["manual trend review"]
  }' | tee /tmp/demo_plan.json | jq
```

Capture plan id:

```bash
PLAN_ID=$(jq -r '.plan.plan_id' /tmp/demo_plan.json)
echo "$PLAN_ID"
```

#### 3.4 Log reproducible run

```bash
curl -s "http://127.0.0.1:8000/api/research/plans/${PLAN_ID}/runs" \
  -H 'Content-Type: application/json' \
  -d '{
    "run_name":"estero_fallback_eval",
    "config":{"mode":"fallback","question":"estero_30y"},
    "metrics":{"net_change_ft":-1.2,"annual_change_ft_per_year":-0.13},
    "findings":"Declining trend in available local period.",
    "reproducibility":{
      "random_seed":42,
      "code_commit":"abc1234",
      "environment":"demo_local",
      "executor":"api_demo"
    },
    "artifacts":[{"path":"outputs/demo/estero_plot.png","kind":"figure"}]
  }' | jq
```

#### 3.5 Generate draft + provenance

```bash
curl -s "http://127.0.0.1:8000/api/research/plans/${PLAN_ID}/draft" \
  -H 'Content-Type: application/json' \
  -d '{
    "target_venue":"arXiv",
    "include_methods_detail":true,
    "citations":["USGS Water Data for the Nation"]
  }' | jq
```

Expected highlights:
- `draft.path`
- `draft.provenance_path`
- `provenance`

## 4. Frontend Demo (Optional)

```bash
cd /Users/salatheoclay/Desktop/GroundwaterGPT/GroundwaterGPT/frontend
npm run dev
```

Open: `http://127.0.0.1:3000`

Demo tabs:
- `AI Assistant`
- `Research Lab` (plan/run/draft flow)

## 5. Benchmark Demo

```bash
cd /Users/salatheoclay/Desktop/GroundwaterGPT/GroundwaterGPT
python3 scripts/run_chat_benchmark.py --output /tmp/chat_benchmark_report.json
cat /tmp/chat_benchmark_report.json | jq '.summary'
```

This demonstrates objective scoring and threshold checks.
