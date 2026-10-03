import json
import time

import pytest
from fastapi.testclient import TestClient

from signaldesk import web


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGNALDESK_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("SIGNALDESK_CONFIG", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    with TestClient(web.create_app()) as c:
        yield c


def test_index_and_status(client):
    assert "SignalDesk" in client.get("/").text
    st = client.get("/api/status").json()
    assert st["api_key_set"] is True and st["job"]["running"] is False


def test_settings_roundtrip(client):
    s = client.get("/api/settings").json()
    assert s["feeds"] and s["watchlist_global"] == []
    payload = {
        "lookback_hours": 12,
        "max_articles": 10,
        "watchlist_global": ["aapl", " spy ", "AAPL"],
        "watchlist_russia": ["sber"],
        "telegram_channels": ["markettwits", ""],
        "disabled_feeds": ["ТАСС"],
    }
    s = client.put("/api/settings", json=payload).json()
    assert s["watchlist_global"] == ["AAPL", "SPY"]
    assert s["watchlist_russia"] == ["SBER"]
    assert s["telegram_channels"] == ["markettwits"]
    assert s["disabled_feeds"] == ["ТАСС"] and s["lookback_hours"] == 12


def test_run_and_reports(client, monkeypatch, tmp_path):
    async def fake_run(settings, market, progress):
        progress(1, "сбор")
        report = {
            "id": "20261003_120000",
            "created_at": "2026-10-03T12:00:00",
            "market": market,
            "analysis": {"recommendations": [{"action": "BUY"}, {"action": "sell"}]},
        }
        out = tmp_path / "data" / "reports"
        out.mkdir(parents=True)
        (out / "20261003_120000.json").write_text(json.dumps(report))
        (out / "20261003_120000.md").write_text("# report")
        return report

    monkeypatch.setattr(web, "run_analysis", fake_run)
    assert client.post("/api/run", json={"market": "russia"}).status_code == 200
    for _ in range(50):
        job = client.get("/api/status").json()["job"]
        if not job["running"]:
            break
        time.sleep(0.05)
    assert job["report_id"] == "20261003_120000" and job["error"] is None

    reports = client.get("/api/reports").json()
    assert reports[0]["counts"] == {"BUY": 1, "HOLD": 0, "SELL": 1}
    assert client.get("/api/reports/20261003_120000").json()["market"] == "russia"
    assert client.get("/api/reports/20261003_120000/markdown").text == "# report"
    assert client.get("/api/reports/..%2Fsecret").status_code == 404
    assert client.delete("/api/reports/20261003_120000").status_code == 200
    assert client.get("/api/reports").json() == []


def test_run_without_key_reports_error(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setattr("signaldesk.config.load_dotenv", lambda: None)
    client.post("/api/run", json={})
    for _ in range(50):
        job = client.get("/api/status").json()["job"]
        if not job["running"]:
            break
        time.sleep(0.05)
    assert "OPENROUTER_API_KEY" in job["error"]


def test_run_validation(client):
    assert client.post("/api/run", json={"market": "mars"}).status_code == 422
