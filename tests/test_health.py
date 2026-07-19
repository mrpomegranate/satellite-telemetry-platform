"""Import smoke test - does not require a live database."""


def test_app_exposes_expected_routes():
    from api.main import app

    paths = set(app.openapi()["paths"])
    assert "/health" in paths
    assert any(p.startswith("/timeseries") for p in paths)
    assert any(p.startswith("/labels") for p in paths)
    assert any(p.startswith("/catalog") for p in paths)
    assert any(p.startswith("/groups") for p in paths)
