"""
E2E test: starts a real Datasette server against a temp SQLite DB populated with
test data, then verifies the JSON API and the dashboard HTML are served correctly.

Requires: datasette installed (pip install -r requirements-dev.txt)
Run with: pytest tests/test_e2e.py -v
"""
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).parent.parent
DATASETTE_YML = REPO_ROOT / "datasette.yml"
STATIC_DIR = REPO_ROOT / "static"
PORT = 18765
BASE_URL = f"http://127.0.0.1:{PORT}"


def wait_for_server(url: str, timeout: int = 10) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=1)
            if r.status_code < 500:
                return True
        except requests.ConnectionError:
            pass
        time.sleep(0.3)
    return False


@pytest.fixture(scope="module")
def db_with_data(tmp_path_factory):
    """Create a temp SQLite DB with known test data."""
    tmp = tmp_path_factory.mktemp("e2e")
    db_path = tmp / "weights.db"

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE visits (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     TEXT NOT NULL UNIQUE,
            cat           TEXT NOT NULL,
            weight_kg     REAL NOT NULL,
            raw_weight_kg REAL NOT NULL,
            confidence    REAL NOT NULL
        )
    """)

    now = datetime.now(timezone.utc)
    rows = []
    for i in range(30):
        ts = now - timedelta(days=i, hours=8)
        rows.append((ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "pirata", 6.5, 6.5, 1.0))
        ts2 = now - timedelta(days=i, hours=14)
        rows.append((ts2.strftime("%Y-%m-%dT%H:%M:%SZ"), "robin", 4.4, 4.4, 1.0))

    conn.executemany(
        "INSERT INTO visits (timestamp, cat, weight_kg, raw_weight_kg, confidence) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(scope="module")
def datasette_server(db_with_data):
    """Start Datasette as a subprocess and yield. Kills it after the module."""
    cmd = [
        sys.executable, "-m", "datasette",
        str(db_with_data),
        "--host", "127.0.0.1",
        "--port", str(PORT),
        "--metadata", str(DATASETTE_YML),
        "--static", f"static:{STATIC_DIR}",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    ready = wait_for_server(f"{BASE_URL}/", timeout=15)
    if not ready:
        proc.terminate()
        proc.wait()
        pytest.fail("Datasette did not start in time")

    yield proc

    proc.terminate()
    proc.wait()


class TestJsonApi:
    def test_versions_endpoint(self, datasette_server):
        r = requests.get(f"{BASE_URL}/-/versions.json")
        assert r.status_code == 200
        data = r.json()
        assert "datasette" in data

    def test_visits_table_returns_data(self, datasette_server):
        r = requests.get(f"{BASE_URL}/weights/visits.json?_shape=array&_size=5")
        assert r.status_code == 200
        data = r.json()
        assert len(data) > 0
        assert "cat" in data[0]
        assert "weight_kg" in data[0]

    def test_pirata_canned_query(self, datasette_server):
        r = requests.get(f"{BASE_URL}/weights/pirata_daily.json?_shape=array")
        assert r.status_code == 200
        data = r.json()
        assert len(data) > 0
        assert all(r["peso"] is not None for r in data)

    def test_robin_canned_query(self, datasette_server):
        r = requests.get(f"{BASE_URL}/weights/robin_daily.json?_shape=array")
        assert r.status_code == 200
        data = r.json()
        assert len(data) > 0

    def test_sql_query_via_api(self, datasette_server):
        sql = "SELECT count(*) AS total FROM visits"
        r = requests.get(f"{BASE_URL}/weights.json?sql={sql}&_shape=array")
        assert r.status_code == 200
        data = r.json()
        assert data[0]["total"] == 60  # 30 days × 2 cats


class TestDashboard:
    def test_dashboard_html_served(self, datasette_server):
        r = requests.get(f"{BASE_URL}/static/dashboard.html")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_dashboard_contains_chart_elements(self, datasette_server):
        r = requests.get(f"{BASE_URL}/static/dashboard.html")
        html = r.text
        assert "chart-pirata" in html
        assert "chart-robin" in html
        assert "Chart.js" in html or "chart.js" in html.lower()

    def test_dashboard_has_both_cat_sections(self, datasette_server):
        r = requests.get(f"{BASE_URL}/static/dashboard.html")
        html = r.text
        assert "Pirata" in html
        assert "Robin" in html
