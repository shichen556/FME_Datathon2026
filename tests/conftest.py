"""Pytest conftest: add starter/ to sys.path so tests can import recommender_v2."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "starter"))