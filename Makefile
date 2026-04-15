demo:
	bash scripts/start_demo.sh

benchmark:
	python3 scripts/run_chat_benchmark.py --mode fallback --enforce-thresholds

test:
	GROUNDWATERGPT_SKIP_AGENT_INIT=1 python3 -m pytest tests/unit/ -q

build:
	cd frontend && npm run build
