"""
Crosscheck de asignación de gato (medida secundaria de robustez).

El invariante del proyecto es «el gato lo da la API»: confiamos en la etiqueta de
Whisker. Este módulo NO reasigna nada; solo verifica. Para cada lectura nueva calcula
la TENDENCIA reciente de cada gato (regresión por mínimos cuadrados sobre sus lecturas
de los últimos `window_days`, con los outliers fuera por MAD para que un pesaje parcial
no la tuerza) y comprueba a qué tendencia se acerca más el peso. Si encaja CLARAMENTE
mejor con otro gato que con el que dice la API (por un margen, para no saltar en
empates), genera una alerta para que la revises por correo.

Causas típicas de un desajuste: un pesaje parcial/doble (el gato entró a medias, o los
dos a la vez) que da un peso fuera del rango del gato etiquetado, o —menos probable—
una etiqueta dudosa de la API. En ambos casos quieres enterarte.
"""
import logging
from statistics import median

from alerts.health import Alert

log = logging.getLogger(__name__)

_TITLES = {"pirata": "Pirata", "robin": "Robin"}


def _mad_filter(pts: list, k: float) -> list:
    """Quita outliers (pesajes parciales/ruido) del ajuste por MAD. pts = [(x, y)]."""
    if len(pts) < 4:
        return pts
    ys = [y for _, y in pts]
    med = median(ys)
    mad = median(sorted(abs(y - med) for y in ys))
    if mad <= 0:
        return pts
    return [(x, y) for (x, y) in pts if abs(y - med) <= k * mad]


def _predict(pts: list, x0: float):
    """Valor de la recta de mínimos cuadrados en x0 (segundos). pts = [(x_sec, y_kg)].

    Con <3 puntos no hay recta fiable: devuelve la media (tendencia plana).
    """
    n = len(pts)
    if n == 0:
        return None
    if n < 3:
        return sum(y for _, y in pts) / n
    sx = sum(x for x, _ in pts)
    sy = sum(y for _, y in pts)
    sxx = sum(x * x for x, _ in pts)
    sxy = sum(x * y for x, y in pts)
    denom = n * sxx - sx * sx
    if denom == 0:
        return sy / n
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope * x0 + intercept


def check_assignments(config: dict, store, new_visits: list) -> list:
    """Devuelve alertas (una por gato afectado) si la tendencia contradice a la API.

    `store` debe ofrecer `load_history_for_cat(cat, days)`. Se llama ANTES de escribir
    las lecturas nuevas, para que la tendencia se construya solo con datos previos.
    """
    cfg = config.get("crosscheck", {})
    if not cfg.get("enabled", True) or not new_visits:
        return []

    window = cfg.get("window_days", 10)
    min_pts = cfg.get("min_points", 3)
    margin = cfg.get("margin_kg", 0.3)
    mad_k = cfg.get("mad_k", 4.0)
    cats = list(config["cats"].keys())

    # Lecturas recientes ya asignadas de cada gato (fiables): base de su tendencia.
    hist = {c: store.load_history_for_cat(c, days=window) for c in cats}

    by_cat: dict = {}   # api_cat -> lista de desajustes
    for v in new_visits:
        t, w, api_cat = v["timestamp"], v["weight_kg"], v["cat"]
        if api_cat not in cats:
            continue

        preds, ok = {}, True
        for c in cats:
            pts = [((r["timestamp"] - t).total_seconds(), r["weight_kg"])
                   for r in hist[c] if r["timestamp"] < t]
            pts = _mad_filter(pts, mad_k)
            if len(pts) < min_pts:
                ok = False
                break
            preds[c] = _predict(pts, 0.0)
        if not ok:
            log.info("Crosscheck omitido para %s @ %s: histórico insuficiente", api_cat, t)
            continue

        dists = {c: abs(w - preds[c]) for c in cats}
        nearest = min(cats, key=lambda c: dists[c])
        gap = dists[api_cat] - dists[nearest]   # cuánto más cerca queda la tendencia rival
        if nearest != api_cat and gap >= margin:
            by_cat.setdefault(api_cat, []).append({
                "t": t, "w": w, "preds": preds, "nearest": nearest, "gap": gap,
            })
            log.warning(
                "Crosscheck: lectura %.3f kg @ %s etiquetada %s pero encaja mejor con %s "
                "(%s, Δ=%.2f kg)",
                w, t, api_cat, nearest,
                ", ".join(f"{c}≈{preds[c]:.2f}" for c in cats), gap,
            )

    alerts = []
    for api_cat, items in by_cat.items():
        lines = []
        for it in items:
            preds = it["preds"]
            trend_txt = ", ".join(f"{_TITLES.get(c, c)}≈{preds[c]:.2f}" for c in cats)
            lines.append(
                f"  - {it['t']:%Y-%m-%d %H:%M} · {it['w']:.2f} kg · API={_TITLES.get(api_cat, api_cat)} "
                f"· tendencia: {trend_txt} → más cerca de {_TITLES.get(it['nearest'], it['nearest'])} "
                f"(Δ={it['gap']:.2f} kg)"
            )
        alerts.append(Alert(
            cat=api_cat,
            severity="warning",
            kind="crosscheck",
            message=(
                f"Crosscheck de asignación: {len(items)} lectura(s) etiquetada(s) por la API "
                f"como {_TITLES.get(api_cat, api_cat)} no encajan con su tendencia reciente "
                f"(encajarían mejor con el otro gato). Suele ser un pesaje parcial/doble; "
                f"revisa por si fuera una etiqueta dudosa. La API manda — no se ha reasignado nada.\n"
                + "\n".join(lines)
            ),
        ))
    return alerts
