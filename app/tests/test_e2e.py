"""
E2E: arranca una Datasette real (instancia ÚNICA, acceso completo) contra una BD
temporal y verifica el dashboard, las canned queries, el favicon y el acceso pleno.

En producción esta instancia va detrás de oauth2-proxy, que es quien deja público
``/`` + canned queries y exige login para el resto. Ese límite se verifica con la
prueba de humo en vivo y con tests/test_oauth_routes.py (no aquí — aquí Datasette es
full por diseño).

Requiere: datasette instalado.  Ejecutar:  pytest tests/test_e2e.py -v
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
PLUGINS_DIR = REPO_ROOT / "plugins"
STATIC_DIR = REPO_ROOT / "static"
PORT = 18765
BASE = f"http://127.0.0.1:{PORT}"


def wait_for_server(url: str, timeout: int = 15) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=1).status_code < 500:
                return True
        except requests.ConnectionError:
            pass
        time.sleep(0.3)
    return False


@pytest.fixture(scope="module")
def db_with_data(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    db_path = tmp / "weights.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL UNIQUE, cat TEXT NOT NULL,
            weight_kg REAL NOT NULL, raw_weight_kg REAL NOT NULL, confidence REAL NOT NULL)
    """)
    conn.execute("CREATE TABLE box_usage (day TEXT PRIMARY KEY, cycles INTEGER NOT NULL)")
    conn.execute("CREATE TABLE robot_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "litter_level REAL, waste_drawer_level REAL, is_online INTEGER)")

    now = datetime.now(timezone.utc)
    rows = []
    for i in range(30):
        rows.append(((now - timedelta(days=i, hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "pirata", 6.5, 6.5, 1.0))
        rows.append(((now - timedelta(days=i, hours=14)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "robin", 4.4, 4.4, 1.0))
    conn.executemany("INSERT INTO visits (timestamp,cat,weight_kg,raw_weight_kg,confidence) "
                     "VALUES (?,?,?,?,?)", rows)
    conn.executemany("INSERT INTO box_usage (day,cycles) VALUES (?,?)",
                     [((now - timedelta(days=i)).strftime("%Y-%m-%d"), 3 + i % 2) for i in range(30)])
    conn.execute("INSERT INTO robot_snapshots (litter_level,waste_drawer_level,is_online) "
                 "VALUES (?,?,?)", (62.0, 18.0, 1))
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(scope="module")
def server(db_with_data):
    cmd = [sys.executable, "-m", "datasette", str(db_with_data),
           "--host", "127.0.0.1", "--port", str(PORT),
           "--metadata", str(DATASETTE_YML),
           "--plugins-dir", str(PLUGINS_DIR),
           "--static", f"static:{STATIC_DIR}"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if not wait_for_server(f"{BASE}/", timeout=15):
        proc.terminate(); proc.wait()
        pytest.fail("Datasette no arrancó a tiempo")
    yield proc
    proc.terminate(); proc.wait()


class TestDashboardAndAssets:
    def test_root_serves_dashboard(self, server):
        r = requests.get(f"{BASE}/")
        assert r.status_code == 200
        assert "chart-pirata" in r.text and "SuPurrMente" in r.text

    def test_favicon_served(self, server):
        r = requests.get(f"{BASE}/favicon.ico")
        assert r.status_code == 200 and r.headers["content-type"] == "image/x-icon"

    def test_dashboard_has_cats_and_google_login(self, server):
        # El dashboard real lo sirve el plugin en "/" (utf-8); /static no fija charset.
        html = requests.get(f"{BASE}/").content.decode("utf-8")
        assert "Pirata" in html and "Robin" in html
        assert "chart.js" in html.lower()
        assert 'href="/weights"' in html             # botón de login → explorador
        assert "Iniciar sesión con Google" in html


class TestCannedQueries:
    def test_cat_daily(self, server):
        r = requests.get(f"{BASE}/weights/cat_daily.json?cat=pirata&_shape=array")
        assert r.status_code == 200
        data = r.json()
        assert data and all(row["peso"] is not None for row in data)

    def test_box_and_status(self, server):
        rb = requests.get(f"{BASE}/weights/box_daily.json?_shape=array")
        rs = requests.get(f"{BASE}/weights/robot_status.json?_shape=array")
        assert rb.status_code == 200 and rb.json()
        assert rs.status_code == 200 and rs.json()[0]["litter_level"] == 62.0


class TestFullAccess:
    """La instancia es full: tablas y SQL responden (el candado lo pone oauth2-proxy)."""
    def test_table_browsing_works(self, server):
        r = requests.get(f"{BASE}/weights/visits.json?_shape=array&_size=5")
        assert r.status_code == 200 and "cat" in r.json()[0]

    def test_arbitrary_sql_works(self, server):
        r = requests.get(f"{BASE}/weights.json?sql=SELECT count(*) AS n FROM visits&_shape=array")
        assert r.status_code == 200 and r.json()[0]["n"] == 60
