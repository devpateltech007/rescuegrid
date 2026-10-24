"""Model output is untrusted: validation, and no coordinates/road ids accepted from the model."""
import pytest
from pydantic import ValidationError

from app.ai.hazard_analyzer import TOOL
from app.models.schemas import HazardAssessment, OperatorAction


def good():
    return dict(hazard_type="BRIDGE_DAMAGE", affected_feature="approach", visual_evidence="x", severity="HIGH",
                suggested_accessibility="LIKELY_BLOCKED", confidence=0.8, uncertainty_notes="u",
                requires_human_review=True, recommended_next_inspection="n")


def test_valid_assessment():
    assert HazardAssessment.model_validate(good()).hazard_type.value == "BRIDGE_DAMAGE"


@pytest.mark.parametrize("field,value", [("hazard_type", "ALIENS"), ("confidence", 3), ("severity", "EXTREME"),
                                         ("suggested_accessibility", "OPEN")])
def test_invalid_rejected(field, value):
    d = good()
    d[field] = value
    with pytest.raises(ValidationError):
        HazardAssessment.model_validate(d)


def test_schema_has_no_geo_fields():
    props = TOOL["toolSpec"]["inputSchema"]["json"]["properties"]
    assert not {"lat", "lon", "latitude", "longitude", "edge_id", "road_id", "osm_id"} & set(props)
    assert "location" not in HazardAssessment.model_fields


@pytest.mark.parametrize("name", ["<script>", "a", "x" * 80, "Robert'); DROP TABLE"])
def test_operator_validation(name):
    with pytest.raises(ValidationError):
        OperatorAction(operator=name)


def test_operator_ok():
    assert OperatorAction(operator="Planning Specialist J. Rivera").operator.startswith("Planning")
