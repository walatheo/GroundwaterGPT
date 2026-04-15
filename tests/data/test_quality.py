"""Data hygiene tests for the manuscript-facing repository surface."""

import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))


PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"


def _canonical_site_csv_files() -> list[Path]:
    """Return canonical site files named ``usgs_<15digits>.csv``."""
    pattern = re.compile(r"^usgs_\d{15}\.csv$")
    return [path for path in DATA_DIR.glob("usgs_*.csv") if pattern.match(path.name)]


class TestCanonicalUsgsData:
    """Ensure the data directory reflects the serving path."""

    def test_canonical_site_files_exist(self):
        files = _canonical_site_csv_files()
        assert len(files) >= 36

    def test_canonical_site_files_are_readable(self):
        for path in _canonical_site_csv_files()[:5]:
            df = pd.read_csv(path)
            assert {"site_no", "datetime", "value"}.issubset(df.columns)
            assert len(df) > 0


class TestRepoHygiene:
    """Ensure stale forecast and snapshot artifacts are absent."""

    def test_no_tracked_timestamped_snapshot_csvs_remain(self):
        """Timestamped pipeline scratch files may be generated locally, but not tracked."""
        result = subprocess.run(
            ["git", "ls-files", "data/usgs_*_20*.csv"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == ""

    def test_no_legacy_forecast_artifacts_remain(self):
        legacy_files = [
            DATA_DIR / "forecast.csv",
            DATA_DIR / "model_comparison.csv",
            DATA_DIR / "feature_importance.csv",
        ]
        assert all(not path.exists() for path in legacy_files)

    def test_no_trained_model_artifacts_remain(self):
        assert list(MODELS_DIR.glob("best_*.joblib")) == []
