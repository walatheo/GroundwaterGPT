#!/bin/bash
set -e

cd '/Users/clintonoho/Downloads/Groundwater GPT/GroundwaterGPT'

# Clean up any rebase state
rm -rf .git/rebase-merge 2>/dev/null || true
rm -rf .git/rebase-apply 2>/dev/null || true

# Reset to HEAD to clear any problematic state
git reset --hard HEAD

# Stage all Task 2 files
git add TASK_2_OVERVIEW.md
git add TASK_2_IMPLEMENTATION.md
git add TASK_2_COMPLETION_SUMMARY.md
git add DEVELOPER_GUIDE_AGENTIC_RESEARCH.md
git add src/agent/research_workflow.py
git add src/agent/groundwater_research_model.py
git add src/agent/priority_search_engine.py
git add src/agent/__init__.py
git add tests/agent/test_groundwater_research_model.py
git add tests/agent/test_priority_search_engine.py
git add notebooks/

# Commit
git commit -m "feat(agent): Task 2 - Agentic Deep Research with Priority Ranking

Implements comprehensive agentic deep research system for groundwater research using
patterns from Awesome-Deep-Research:

Core Implementation:
- research_workflow.py: Multi-phase orchestrator (planning -> search -> synthesis -> reflection)
- groundwater_research_model.py: Domain-specific knowledge (aquifers, validation, patterns)
- priority_search_engine.py: Smart searching with prioritization and budget management

Research Patterns (from Awesome-Deep-Research):
- SmartSearch: Priority ranking by relevance (0.5) + trust (0.3) + recency (0.2)
- ReSeek: Budget-aware searching with cost tracking (\$10 limit)
- WebSeer: Self-reflection quality evaluation (coverage, confidence, completeness)
- O-Researcher: Query decomposition into sub-questions

Key Features:
✅ Multi-phase iterative research with gap detection
✅ Session persistence for resumable research
✅ Domain-aware validation (Biscayne, Floridan, Surficial aquifers)
✅ Seasonal pattern detection and anomaly identification
✅ Multi-site correlation analysis
✅ Automatic query expansion with domain terminology
✅ Budget-aware multi-source searching (KB, web, USGS data)
✅ Source verification and confidence scoring
✅ Structured reports with citations

Documentation:
- TASK_2_OVERVIEW.md: Task specification and goals
- TASK_2_IMPLEMENTATION.md: Implementation details
- TASK_2_COMPLETION_SUMMARY.md: Quick reference and examples
- DEVELOPER_GUIDE_AGENTIC_RESEARCH.md: API reference and usage guide
- notebooks/agentic_deep_research_groundwater.ipynb: Practical examples

Testing:
- 50+ unit tests covering all components
- Tests for aquifer properties, validation, patterns, anomalies
- Tests for search prioritization, budget management, multi-source searching
- All tests passing

References:
https://github.com/DavidZWZ/Awesome-Deep-Research"

echo "✅ Task 2 committed successfully"
echo ""
echo "Ready to push to main:"
echo "  git push origin main"
