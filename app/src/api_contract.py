"""API contract checks.

The Whisker/LR4 API is unofficial and has changed before (weights used to be read
from the wrong place entirely). This module validates that each fetch still returns
data in the shape we depend on, and returns human-readable issues. main.py turns any
issue into a critical alert so we get told to re-analyse the API instead of silently
storing nothing — or worse, wrong numbers.

Kept free of pylitterbot imports so it can be unit-tested with plain dicts.
"""
from typing import Optional


def validate(known_cats: set, pets: list[dict], config: dict) -> list[str]:
    """Return a list of contract violations (empty = healthy).

    `pets` is a normalised summary built by the fetcher, one dict per API pet:
        {
          "name": str,            # raw pet name from the API
          "cat":  str,            # normalised key ('robin')
          "readings_kg": [float], # ALL readings in its history, already lbs→kg
          "error": str | None,    # exception text if the history call failed
          "ok_shape": bool,       # False if a measurement lacked timestamp/weight
        }
    """
    issues: list[str] = []

    if not pets:
        return ["La API no devolvió ninguna mascota (account.pets vacío)"]

    api_cats = {p["cat"] for p in pets}
    for cat in sorted(known_cats):
        if cat not in api_cats:
            issues.append(
                f"Falta el gato esperado '{cat}' — la API solo trae {sorted(api_cats)}"
            )

    for p in pets:
        if p.get("error"):
            issues.append(f"Error leyendo el historial de {p['name']}: {p['error']}")
        elif not p.get("ok_shape", True):
            issues.append(
                f"Mediciones de {p['name']} con formato inesperado "
                "(falta timestamp o weight)"
            )

    total = sum(len(p.get("readings_kg", [])) for p in pets)
    if total == 0 and not any(p.get("error") for p in pets):
        issues.append("Las mascotas existen pero ningún historial de peso tiene datos")

    # Unit/format-change guard: compare each cat's median reading to its seed weight.
    # A regression to pounds is ~×2.2 for BOTH cats — an absolute kg band would miss
    # the lighter cat (a Robin in lbs ~9.7 still looks like a plausible heavy cat).
    health = config.get("api_health", {})
    hi_ratio = health.get("max_weight_ratio", 1.8)
    lo_ratio = health.get("min_weight_ratio", 0.55)
    cats_cfg = config.get("cats", {})
    for p in pets:
        readings = p.get("readings_kg", [])
        seed = cats_cfg.get(p["cat"], {}).get("seed_weight_kg")
        if not readings or not seed:
            continue
        median = sorted(readings)[len(readings) // 2]
        ratio = median / seed
        if ratio > hi_ratio or ratio < lo_ratio:
            issues.append(
                f"Pesos de {p['name']} ~{median:.1f} kg vs esperado ~{seed:.1f} kg "
                f"(×{ratio:.1f}) — ¿cambió la unidad o el formato? (p. ej. libras en vez de kg)"
            )

    return issues


def describe_meta(firmware: Optional[str], library_version: Optional[str],
                  model: Optional[str], serial: Optional[str]) -> str:
    """One-line summary of the device/library versions in use, for logs/alerts."""
    return (
        f"modelo={model!r} serial={serial!r} firmware={firmware!r} "
        f"pylitterbot={library_version!r}"
    )
