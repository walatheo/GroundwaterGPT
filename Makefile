demo:
	bash scripts/start_demo.sh

benchmark:
	python3 scripts/run_chat_benchmark.py --mode fallback --enforce-thresholds

benchmark-llm-smoke:
	python3 scripts/run_agent_benchmark.py --limit 1 --output agent_benchmark_report.json

benchmark-chart-llm:
	python3 scripts/run_chart_explainability_benchmark.py --enforce-thresholds

benchmark-evidence-guided:
	python3 scripts/run_evidence_guided_synthesis_benchmark.py --enforce-thresholds

benchmark-interpretation:
	python3 scripts/run_interpretation_benchmark.py --disable-llm --enforce-thresholds

benchmark-interpretation-llm:
	python3 scripts/run_interpretation_benchmark.py --enforce-thresholds

review-chat:
	python3 scripts/run_chat_review.py --skip-agent-init

review-chat-llm:
	python3 scripts/run_chat_review.py --skip-agent-init --enable-llm

benchmark-llm:
	python3 scripts/run_agent_benchmark.py --output agent_benchmark_report.json

test:
	GROUNDWATERGPT_SKIP_AGENT_INIT=1 python3 -m pytest tests/unit/ -q

build:
	cd frontend && npm run build
