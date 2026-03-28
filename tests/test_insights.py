import pytest
from insights import _build_insights_prompt, _build_overview_prompt, CHART_CONTEXTS


SAMPLE_ROW = {
    "month": 9, "year": 2025, "patients": 125,
    "discharge_los_me": 3.47, "discharge_los_peers": 3.8, "discharge_los_pctile": 13,
    "admit_los_me": 5.1, "admit_los_peers": 5.5, "admit_los_pctile": 30,
    "admission_rate_me": 11.2, "admission_rate_peers": 17.6, "admission_rate_pctile": 15,
    "bed_request_me": 143, "bed_request_peers": 171, "bed_request_pctile": 28,
    "returns72_me": 2.1, "returns72_peers": 2.5, "returns72_pctile": 35,
    "readmits72_me": 0.8, "readmits72_peers": 1.2, "readmits72_pctile": 25,
    "rad_orders_me": 31, "rad_orders_peers": 35, "rad_orders_pctile": 40,
    "lab_orders_me": 70, "lab_orders_peers": 72, "lab_orders_pctile": 45,
    "pts_per_hour_me": 1.8, "pts_per_hour_peers": 1.6, "pts_per_hour_pctile": 70,
    "discharge_rate_me": 88.8, "discharge_rate_peers": 82.4, "discharge_rate_pctile": 75,
    "icu_rate_me": 5.0, "icu_rate_peers": 6.0, "icu_rate_pctile": 40,
    "rad_admit_me": 61, "rad_admit_peers": 49,
    "rad_disc_me": 22, "rad_disc_peers": 30,
    "esi1": 0.8, "esi2": 20.0, "esi3": 49.6, "esi4": 23.2, "esi5": 6.4,
    "billing_level3": 5, "billing_level4": 57, "billing_level5": 38,
}


def test_chart_contexts_keys():
    expected_keys = {
        "dischargeLOS", "admitLOS", "admissionRate", "bedRequest",
        "returns72", "readmits72", "icuRate", "radOrders", "labOrders",
        "ptsPerHour", "dischargeRate", "volume", "radByDispo", "esiChart",
        "pctTable", "overview",
    }
    assert expected_keys == set(CHART_CONTEXTS.keys())


def test_build_insights_prompt_returns_string():
    prompt = _build_insights_prompt("dischargeLOS", SAMPLE_ROW, [SAMPLE_ROW])
    assert isinstance(prompt, str)
    assert "Discharge" in prompt
    assert "3.47" in prompt


def test_build_insights_prompt_unknown_key_returns_none():
    result = _build_insights_prompt("nonexistent", SAMPLE_ROW, [SAMPLE_ROW])
    assert result is None


def test_build_overview_prompt_returns_string():
    prompt = _build_overview_prompt(SAMPLE_ROW, [SAMPLE_ROW])
    assert isinstance(prompt, str)
    assert "Sep 2025" in prompt
    assert "3.47" in prompt


def test_build_insights_prompt_overview_delegates():
    prompt = _build_insights_prompt("overview", SAMPLE_ROW, [SAMPLE_ROW])
    assert prompt is not None
    assert "Sep 2025" in prompt
