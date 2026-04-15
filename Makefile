demo:
	bash scripts/start_demo.sh

benchmark:
	python3 scripts/run_chat_benchmark.py --mode fallback --enforce-thresholds

benchmark-llm-smoke:
	python3 scripts/run_agent_benchmark.py --limit 1 --output agent_benchmark_report.json

benchmark-chart-llm:
	python3 scripts/run_chart_explainability_benchmark.py --enforce-thresholds

benchmark-llm:
	python3 scripts/run_agent_benchmark.py --output agent_benchmark_report.json

test:
	GROUNDWATERGPT_SKIP_AGENT_INIT=1 python3 -m pytest tests/unit/ -q

build:
	cd frontend && npm run build
