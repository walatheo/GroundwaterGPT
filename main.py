#!/usr/bin/env python3
"""GroundwaterGPT - Main Entry Point.

Run the application with:
    python main.py [command]

Commands:
    app         - Start the main Streamlit research interface
    dashboard   - Open the dashboard visualization
    learn       - Run continuous learning to fetch USGS data
    train       - Train ML models
    test        - Run test suite

Examples:
    python main.py app          # Start research chat
    python main.py learn        # Fetch new USGS data
    python main.py dashboard    # Open dashboard
"""

import subprocess
import sys
from pathlib import Path

# Add src to path
ROOT_DIR = Path(__file__).parent
SRC_DIR = ROOT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))


def run_app():
    """Start the Streamlit research chat interface."""
    print("🌊 Starting GroundwaterGPT Research Interface...")
    subprocess.run([
        "streamlit", "run", 
        str(SRC_DIR / "ui" / "research_chat.py"),
        "--server.port", "8502"
    ])


def run_dashboard():
    """Open the dashboard visualization."""
    import webbrowser
    dashboard_path = ROOT_DIR / "outputs" / "plots" / "dashboard.html"
    if dashboard_path.exists():
        webbrowser.open(f"file://{dashboard_path}")
        print(f"📊 Opened dashboard: {dashboard_path}")
    else:
        print("❌ Dashboard not found. Run 'python main.py train' first.")


def run_learn():
    """Run continuous learning to fetch USGS data."""
    print("🧠 Starting continuous learning...")
    from src.data.continuous_learning import ContinuousLearner
    learner = ContinuousLearner()
    stats = learner.fetch_all_florida_aquifer_data()
    print(f"✅ Learning complete: {stats}")


def run_train():
    """Train ML models."""
    print("🎯 Training models...")
    exec(open(SRC_DIR / "ml" / "train_groundwater.py").read())


def run_tests():
    """Run the test suite."""
    print("🧪 Running tests...")
    subprocess.run(["pytest", "tests/", "-v"])


def show_help():
    """Show help message."""
    print(__doc__)
    print("\n📁 Project Structure:")
    print("  src/agent/     - AI research agent")
    print("  src/data/      - Data collection")
    print("  src/ml/        - Machine learning")
    print("  src/ui/        - User interfaces")
    print("  docs/          - Documentation")
    print("  resources/     - PDFs & references")
    print("  knowledge_base/ - ChromaDB vector store")
    print("  outputs/       - Generated plots & reports")


if __name__ == "__main__":
    commands = {
        "app": run_app,
        "dashboard": run_dashboard,
        "learn": run_learn,
        "train": run_train,
        "test": run_tests,
        "help": show_help,
    }
    
    if len(sys.argv) < 2:
        show_help()
        sys.exit(0)
    
    cmd = sys.argv[1].lower()
    if cmd in commands:
        commands[cmd]()
    else:
        print(f"❌ Unknown command: {cmd}")
        show_help()
        sys.exit(1)
