"""WGS84 <-> local metric (UTM 17N) transforms. All geometry math happens in UTM."""
from __future__ import annotations

import numpy as np
from pyproj import Transformer

from app.config import GEO_CRS, LOCAL_CRS

_to_local = Transformer.from_crs(GEO_CRS, LOCAL_CRS, always_xy=True)
_to_geo = Transformer.from_crs(LOCAL_CRS, GEO_CRS, always_xy=True)


def to_local(lon, lat):
    """lon/lat (deg) -> easting/northing (m). Accepts scalars or arrays."""
    return _to_local.transform(lon, lat)


def to_geo(x, y):
    """easting/northing (m) -> lon/lat (deg)."""
    return _to_geo.transform(x, y)


def to_geo_array(xy: np.ndarray) -> np.ndarray:
    lon, lat = _to_geo.transform(xy[:, 0], xy[:, 1])
    return np.column_stack([lon, lat])
