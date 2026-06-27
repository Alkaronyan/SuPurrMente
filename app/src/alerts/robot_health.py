"""Robot-level alerts (not per-cat): litter low, waste drawer full, robot offline.

Operates on a fetcher.FetchResult. Returns Alert objects (cat='caja') so they ride
the same email + cooldown-dedup path as the health alerts.
"""
from alerts.health import Alert


def check(result, config: dict) -> list[Alert]:
    cfg = config.get("robot_health", {})
    low = cfg.get("litter_low_pct", 10)
    full = cfg.get("drawer_full_pct", 90)
    alerts = []

    if result.litter_level is not None and result.litter_level <= low:
        alerts.append(Alert(
            cat="caja", severity="warning", kind="litter_low",
            message=f"Nivel de arena bajo: {result.litter_level:.0f}% (umbral {low}%) — rellenar",
        ))

    if result.waste_drawer_level is not None and result.waste_drawer_level >= full:
        alerts.append(Alert(
            cat="caja", severity="warning", kind="drawer_full",
            message=f"Cajón de residuos casi lleno: {result.waste_drawer_level:.0f}% (umbral {full}%) — vaciar",
        ))

    if result.is_online is False:
        alerts.append(Alert(
            cat="caja", severity="critical", kind="offline",
            message="El robot está desconectado (is_online=False) — podrían perderse datos",
        ))

    return alerts
