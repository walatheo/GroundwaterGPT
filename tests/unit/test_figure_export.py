"""Tests for the publication figure export endpoint."""

from fastapi.testclient import TestClient


def _payload(with_precip: bool = False):
    rows = [
        {"date": "2020-01-01", "well_a": 10.0, "well_b": 9.5},
        {"date": "2020-02-01", "well_a": 10.2, "well_b": 9.7},
        {"date": "2020-03-01", "well_a": 10.5, "well_b": 9.9},
    ]
    if with_precip:
        for i, row in enumerate(rows):
            row["precip_mm"] = 40.0 + i * 10
    return {
        "chart_payload": {
            "title": "Test",
            "x_label": "Month",
            "y_label": "ft",
            "series": [
                {"key": "well_a", "name": "Well A", "color": "#2563eb"},
                {"key": "well_b", "name": "Well B", "color": "#dc2626"},
            ],
            "data": rows,
            "annotations": [
                {
                    "type": "changepoint",
                    "site_id": "well_a",
                    "date": "2020-02-01",
                    "pre_slope": 0.1,
                    "post_slope": -0.3,
                    "highlight": True,
                }
            ],
        },
        "format": "svg",
        "dpi": 96,
    }


def _client():
    from api.main import app

    return TestClient(app)


def test_export_svg_returns_valid_svg_bytes():
    client = _client()
    resp = client.post("/api/figures/export", json=_payload())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg")
    assert resp.content.startswith(b"<?xml") or b"<svg" in resp.content[:200]


def test_export_png_returns_png_magic_bytes():
    client = _client()
    body = _payload()
    body["format"] = "png"
    resp = client.post("/api/figures/export", json=body)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_export_renders_with_precip_axis():
    client = _client()
    resp = client.post("/api/figures/export", json=_payload(with_precip=True))
    assert resp.status_code == 200
    assert len(resp.content) > 1000


def test_export_rejects_empty_payload():
    client = _client()
    resp = client.post(
        "/api/figures/export",
        json={"chart_payload": {"data": [], "series": []}, "format": "svg"},
    )
    assert resp.status_code == 400


def test_export_validates_format():
    client = _client()
    body = _payload()
    body["format"] = "jpeg"
    resp = client.post("/api/figures/export", json=body)
    assert resp.status_code == 422
