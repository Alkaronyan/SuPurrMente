import asyncio
import logging
import sys
from pathlib import Path

import yaml

import api_contract
import crosscheck
import whisker_auth
from fetcher import fetch_new_visits
from classifier import Classifier
from storage.sqlite_store import SQLiteStore
from storage.csv_store import CsvStore
from alerts.health import HealthChecker, Alert
from alerts import robot_health
from alerts.email_sender import EmailSender

log = logging.getLogger(__name__)


def _send_with_cooldown(config, store, alerts) -> None:
    """Send alerts, suppressing any (cat+kind) already sent within the cooldown."""
    if not alerts:
        log.info("No alerts to send")
        return
    cooldown_h = config.get("alerts", {}).get("cooldown_hours", 24)
    already_sent = store.recent_alert_fingerprints(cooldown_h)
    fresh = [a for a in alerts if a.fingerprint() not in already_sent]

    suppressed = len(alerts) - len(fresh)
    if suppressed:
        log.info("Suppressed %d alert(s) still within %dh cooldown", suppressed, cooldown_h)
    if not fresh:
        log.info("All alerts already notified within cooldown — nothing to send")
        return

    log.info("Sending %d alert(s)", len(fresh))
    EmailSender(config).send(fresh)
    store.record_sent_alerts([a.fingerprint() for a in fresh])


def load_config() -> dict:
    for path in [Path("/app/config.yml"), Path("config.yml")]:
        if path.exists():
            with open(path) as f:
                return yaml.safe_load(f)
    raise FileNotFoundError("config.yml not found")


async def run_pipeline(config: dict) -> None:
    store = SQLiteStore(config)
    csv = CsvStore(config)

    try:
        result = await fetch_new_visits(config, last_timestamp=store.last_timestamp())
    except whisker_auth.WhiskerAuthRequired as e:
        # Sin token válido no podemos recoger datos: avisa (1×/día) con el enlace al
        # formulario de login y termina el ciclo limpiamente.
        log.warning("Sesión de Whisker no disponible: %s", e)
        login_url = config.get("whisker", {}).get("login_url", "")
        alert = Alert(
            cat="sistema", severity="critical", kind="whisker_login",
            message=("No hay sesión activa con Whisker (token ausente o caducado). "
                     "La recogida de datos está parada. Inicia sesión aquí para "
                     f"reactivarla: {login_url}"),
        )
        _send_with_cooldown(config, store, [alert])
        return

    # ── API health: contract + version registry ───────────────────────────────
    # These must be evaluated even when there are 0 new visits — a broken API or a
    # firmware change is exactly the case where no data comes through.
    system_alerts = []

    log.info("API meta: %s", api_contract.describe_meta(
        result.firmware, result.library_version, result.model, result.serial))
    change = store.record_api_meta(
        result.firmware, result.library_version, result.model, result.serial)
    if change:
        system_alerts.append(Alert(
            cat="sistema", severity="warning", kind="version_change",
            message=(
                f"Cambio de versión detectado en '{change['field']}': "
                f"{change['old']!r} → {change['new']!r}. Revisar que el mapeo de la "
                "API (fetcher.py) sigue siendo correcto."
            ),
        ))

    if result.api_issues:
        system_alerts.append(Alert(
            cat="sistema", severity="critical", kind="api_contract",
            message="La API no devuelve los datos esperados — "
                    + " | ".join(result.api_issues),
        ))

    # Robot-level data: daily box usage + state snapshot + low/full/offline alerts.
    store.upsert_box_usage(result.cycle_history)
    store.record_robot_snapshot(
        result.litter_level, result.waste_drawer_level, result.is_online, result.last_seen)
    system_alerts.extend(robot_health.check(result, config))

    # ── Store new readings ────────────────────────────────────────────────────
    visits = result.visits
    crosscheck_alerts = []
    if visits:
        log.info("Fetched %d new visit(s)", len(visits))
        # The API already identifies the cat per reading; the classifier only validates.
        classifier = Classifier(config, history=store.load_history())
        classified = [classifier.classify_known(v) for v in visits]
        # Secondary robustness: does each reading's weight match its API-assigned cat's
        # recent trend? Run BEFORE writing so the trend uses only prior data. A clear
        # mismatch (partial/double weighing or a dubious label) gets emailed.
        crosscheck_alerts = crosscheck.check_assignments(config, store, visits)
        store.write(classified)
        # Tag the backup CSV with the API version so it rotates if Whisker changes it.
        api_version = None
        if result.firmware or result.library_version:
            api_version = f"{result.firmware} | pylitterbot {result.library_version}"
        csv.write(classified, api_version=api_version)
    else:
        log.info("No new visits to process")

    # ── Health alerts (only meaningful with data present) ─────────────────────
    health_alerts = HealthChecker(config, store).check_all()

    _send_with_cooldown(config, store, system_alerts + crosscheck_alerts + health_alerts)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    config = load_config()

    try:
        asyncio.run(run_pipeline(config))
    except Exception:
        log.exception("Pipeline failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
