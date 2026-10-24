"""Central configuration. Secrets never live here — AWS credentials come from the
environment / instance role via the default boto3 credential chain."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
GEO = DATA / "geography"
TERRAIN = DATA / "terrain"
ROADS = DATA / "road_graph"
IMAGERY = DATA / "imagery"
SCENARIOS = DATA / "scenarios"
FIXTURES = DATA / "demo_fixtures"
RUNTIME = DATA / "runtime"  # git-ignored: sqlite, generated scans, renders
FRONTEND_DIST = ROOT / "frontend" / "dist"

# Local metric CRS for all calculations (UTM zone 17N covers western NC).
LOCAL_CRS = "EPSG:32617"
GEO_CRS = "EPSG:4326"

# OSM way id of the Whitson Avenue bridge (bridge=yes, SR 2727), found via Overpass.
WHITSON_BRIDGE_OSM_WAY = 388972121


@lru_cache
def aws_config() -> dict:
    p = DATA / "aws_config.json"
    return json.loads(p.read_text()) if p.exists() else {}


@lru_cache
def study_area() -> dict:
    p = GEO / "study_area.json"
    return json.loads(p.read_text()) if p.exists() else {}


class Settings:
    region: str = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    bucket: str = os.getenv("RESCUEGRID_BUCKET", aws_config().get("bucket", ""))
    model_id: str = os.getenv("RESCUEGRID_BEDROCK_MODEL", aws_config().get("bedrock_model_id", ""))
    briefing_model_id: str = os.getenv("RESCUEGRID_BRIEFING_MODEL", aws_config().get("bedrock_model_id", ""))
    bedrock_enabled: bool = os.getenv("RESCUEGRID_BEDROCK", "1") != "0"
    s3_enabled: bool = os.getenv("RESCUEGRID_S3", "1") != "0"
    # Offline fixture is only used when explicitly enabled and is always labeled.
    allow_offline_fixture: bool = os.getenv("RESCUEGRID_ALLOW_OFFLINE_FIXTURE", "0") == "1"
    seed: int = int(os.getenv("RESCUEGRID_SEED", "20240927"))
    unknown_penalty: float = float(os.getenv("RESCUEGRID_UNKNOWN_PENALTY", "1.3"))
    suspected_penalty: float = float(os.getenv("RESCUEGRID_SUSPECTED_PENALTY", "25"))
    db_path: Path = Path(os.getenv("RESCUEGRID_DB", str(RUNTIME / "rescuegrid.sqlite")))


settings = Settings()
