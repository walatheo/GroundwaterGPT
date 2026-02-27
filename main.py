#!/usr/bin/env python3
"""GroundwaterGPT - Main Entry Point.

Run the application with:
    python main.py [command]

Commands:
    server      - Start FastAPI backend + Vite frontend dev servers
    app         - Start the main Streamlit research interface
    viz         - Start the integrated visualization app
    dashboard   - Open the dashboard visualization (HTML)
    learn       - Run continuous learning to fetch USGS data
    train       - Train ML models
    test        - Run test suite

Examples:
    python main.py server       # Start API + React dashboard
    python main.py app          # Start research chat
    python main.py viz          # Start visualization app
    python main.py learn        # Fetch new USGS data
    python main.py dashboard    # Open dashboard (HTML file)
"""

import subprocess
import sys
from pathlib import Path

# Add src to path
ROOT_DIR = Path(__file__).parent
SRC_DIR = ROOT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))


def run_server():
    """Start FastAPI backend (port 8000) and Vite frontend (port 3000)."""
    import signal

    print("🌊 Starting GroundwaterGPT Dashboard...")
    print("   API:      http://127.0.0.1:8000/docs")
    print("   Frontend: http://localhost:3000")
    print("   Press Ctrl+C to stop both servers.\n")

    api_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--reload",
        ],
        cwd=str(ROOT_DIR),
    )

    frontend_dir = ROOT_DIR / "frontend"
    vite_proc = subprocess.Popen(
        ["npx", "vite", "--port", "3000"],
        cwd=str(frontend_dir),
    )

    def _shutdown(sig, frame):
        api_proc.terminate()
        vite_proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        api_proc.wait()
    except KeyboardInterrupt:
        _shutdown(None, None)


def run_app():
    """Start the Streamlit research chat interface."""
    print("🌊 Starting GroundwaterGPT Research Interface...")
    subprocess.run(
        [
            "streamlit",
            "run",
            str(SRC_DIR / "ui" / "research_chat.py"),
            "--server.port",
            "8502",
        ]
    )


def run_viz():
    """Start the integrated visualization app with research + charts."""
    print("📊 Starting GroundwaterGPT Integrated App (Research + Visualization)...")
    subprocess.run(
        ["streamlit", "run", str(SRC_DIR / "ui" / "integrated_app.py"), "--server.port", "8501"]
    )


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
    subprocess.run([sys.executable, str(SRC_DIR / "ml" / "train_groundwater.py")])


def run_tests():
    """Run the test suite."""
    print("🧪 Running tests...")
    subprocess.run(["pytest", "tests/", "-v"])


def show_help():
    """Show help message."""
    print(__doc__)
    print("\n📁 Project Structure:")
    print("  api/           - FastAPI backend (routes, helpers)")
    print("  frontend/      - React + Vite dashboard")
    print("  src/agent/     - AI research agent")
    print("  src/data/      - Data collection")
    print("  src/ml/        - Machine learning")
    print("  src/ui/        - Streamlit interfaces")
    print("  docs/          - Documentation")
    print("  resources/     - PDFs & references")
    print("  knowledge_base/ - ChromaDB vector store")
    print("  outputs/       - Generated plots & reports")


if __name__ == "__main__":
    commands = {
        "server": run_server,
        "app": run_app,
        "viz": run_viz,
        "visualization": run_viz,
        "dashboard": run_dashboard,
        "learn": run_learn,
        "train": run_train,
        "test": run_tests,
        "help": show_help,
        "--help": show_help,
        "-h": show_help,
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
