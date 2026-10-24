import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
# Unit tests never call AWS. The live Bedrock path is covered by scripts/e2e_demo.py.
os.environ.setdefault("RESCUEGRID_BEDROCK", "0")
os.environ.setdefault("RESCUEGRID_S3", "0")
os.environ.setdefault("RESCUEGRID_DB", str(ROOT / "data" / "runtime" / "test.sqlite"))
