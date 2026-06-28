# 2026-06-28 — Crosscheck de asignación, revisión de datos y limpieza

Sesión posterior al monolito+token. Tres bloques: revisar los datos migrados, añadir
una red de robustez secundaria a la clasificación, y limpiar/reordenar el repo.

## 1. Revisión de los datos migrados (no se tocó nada)

Tras una migración nueva (BD con 4825 visitas, 2024-09-30 → 2026-06-26), se estudió si
había rarezas antes de darlos por buenos.

- **Dos clusters bien separados:** Robin pico en 4.5 kg, Pirata en 6.5–6.75 kg. **Cero
  cruces** de clasificación (ningún Robin ≥5.5, ningún Pirata <5.5).
- **Colas implausibles (~34 lecturas, 0.7%):** Robin <3 kg (hasta 1.1) y Pirata >7.75
  (hasta 9.1). Pesajes parciales / doble ocupación.
- **Decisión del usuario: conservar TODO en raw.** Los outliers pueden ser señal (p.ej.
  muchas visitas seguidas = estrés) y se confía en la robustez estadística aguas abajo.
  No se filtra ni se borra nada.

### La asignación dura de la banda 5–6 kg, validada
La migración clasifica con un umbral **estático ≈ 5.5 kg**: `Classifier._refresh_averages`
solo mira los últimos 14 días *desde ahora*, y los datos históricos son más viejos → la
media móvil nunca se mueve de las semillas (6.6/4.4) y el umbral se queda en su punto
medio. Las 66 lecturas dudosas (`confidence < 0.5`) son las de peso 5.0–6.0.

Se construyó un script de estudio (regresión de la tendencia de los ~10 días previos por
gato, outliers fuera por MAD) para reasignar esas dudosas por cercanía a la tendencia, en
vez de por el umbral duro. Resultado: **65/66 coinciden** con lo guardado. La banda
[5.5,6.0)→Pirata es **61/61 correcta**. La única discrepancia (2025-01-11, 5.40 kg,
guardada robin) la tendencia la daría a Pirata — y es justo enero-2025, cuando ambos
gatos pesaban menos que sus semillas: el periodo donde un umbral fijo de 5.5 más falla.
Conclusión: la asignación está bien; de 4825 filas solo 1 cambiaría. El script fue
throwaway; su lógica se promovió a producción (ver bloque 2).

## 2. Crosscheck de asignación (`crosscheck.py`)

Medida **secundaria** de robustez, pedida por el usuario: en cada ciclo, para cada
lectura nueva, contrastar el peso contra la **tendencia reciente** del gato que dice la
API; si encaja claramente mejor con el otro gato, **mandar email**.

- **Cómo:** regresión por mínimos cuadrados sobre las lecturas de cada gato en los
  `window_days` previos, con outliers fuera por **MAD** (para que un pesaje parcial no
  tuerza la recta — los datos NO se filtran, solo el ajuste). Predice el peso esperado de
  cada gato en el instante de la lectura y mira a cuál se acerca más.
- **Cuándo avisa:** solo si la tendencia rival queda al menos `margin_kg` más cerca
  (evita saltar en empates) y hay ≥`min_points` lecturas claras para fiarse.
- **No reasigna nada** — respeta el invariante "el gato lo da la API". Un desajuste señala
  pesaje parcial/doble o, raramente, etiqueta dudosa. Una alerta por gato afectado,
  agregando las lecturas; va por el cooldown normal de 24h (`kind="crosscheck"`).
- **Integración:** `main.run_pipeline` lo llama **antes** de escribir (para que la
  tendencia use solo datos previos) y suma sus alertas a `_send_with_cooldown`.
- **Config** (`config.yml` → `crosscheck`): `enabled`, `window_days: 10`, `min_points: 3`,
  `margin_kg: 0.3`, `mad_k: 4.0`.
- **Tests:** `tests/test_crosscheck.py` (8): detecta discrepancia, no salta si coincide /
  en empate / con histórico insuficiente / deshabilitado, ignora outliers por MAD, agrega
  por gato. Smoke contra la BD real: predijo pirata≈6.62 / robin≈4.47 y marcó una lectura
  sintética de 5.8 kg etiquetada robin. **Suite total: 151 verde.**

## 3. Diagnóstico: por qué no había datos de 27–28 jun

La última lectura en BD era 2026-06-26 08:16. Un fetch de solo lectura mostró que **la
propia API de Whisker no tiene nada posterior** (`fetch_weight_history` devuelve 38
lecturas, todas 22→26 jun; `last_seen` del robot = 2026-06-15). Dos gatos no pasan 2 días
sin arenero → **el LR4 dejó de sincronizar con la nube** ~la mañana del 26. El pipeline
está sano (`api_issues: []`). En producción la alerta de **ausencia** (24h) avisaría; en
dev no corre el scheduler. Acción del usuario: revisar el robot físico (WiFi/enchufe).

## 4. Limpieza y reordenación

- **Borrados** (obsoletos): `app/scripts/inspect_*.py` (5 scripts one-off de exploración
  de la API; usaban `WHISKER_USERNAME/PASSWORD` ya eliminados y el viejo servicio
  `tracker`). Dir `app/scripts/` eliminado. Diagnóstico vivo que queda: `verify_token.py`.
- **`.env.example`** borrado (redundante con `.env.age` + `setup.sh`). `setup.sh`
  actualizado para no depender de él.
- **`.env.hint`** desvinculado de git (`git rm --cached`) y añadido a `.gitignore`:
  contenía una pista de la passphrase en texto plano; se conserva **local** como
  recordatorio, fuera del repo.
- Tras esto la raíz queda al mínimo: `.env.age`, `.gitattributes`, `.gitignore`,
  `CLAUDE.md`, `Makefile`, `README.md`, `docker-compose.yml`, `setup.sh`.
- **No** se reestructuraron los ficheros de runtime de `app/` (entrypoint, run-*.sh,
  supervisord.conf, *.cfg): el Dockerfile y supervisord referencian sus rutas; moverlos
  es riesgo alto sin beneficio. Se dejan planos a propósito.
- Docs principales (CLAUDE.md, README.md, ARCHITECTURE.md, CONTEXT.md) actualizados con lo
  mínimo: crosscheck y la nueva estructura. El detalle, aquí.

## 5. Dashboard: ejes temporales sincronizados (`static/dashboard.html`)

Trabajado en paralelo por otro agente, incluido en el mismo commit. Las tres gráficas
apiladas (peso de Pirata, peso de Robin, uso de la caja) ahora comparten el **mismo eje
temporal**, así que las fechas quedan alineadas en vertical:

- En los ejes X de tipo `time` (los dos de peso y el de la caja) se inyecta `min`/`max`
  de forma condicional desde el rango seleccionado: `...(start && { min: isoDate(start) })`
  / `...(end && { max: isoDate(end) })`.
- `render()` pasó a `async` y construye las tres gráficas en paralelo
  (`await Promise.all([...])`).
- En modo **"toda la historia"** no hay `min`/`max` explícito y cada gráfica auto-escala a
  sus propios datos (se desalineaban). Tras renderizar, se lee el rango X real de cada eje
  ya pintado, se calcula el **span global** (`min` de los mínimos, `max` de los máximos) y
  se fuerza en las tres con `chart.update('none')`. Resultado: ejes alineados también sin
  filtro de fechas.
- **Separado el JS del HTML:** todo el `<script>` inline pasó a `static/dashboard.js`
  (cargado como script clásico al final del `body`, así las funciones siguen globales y los
  `onclick`/`onchange` del HTML las encuentran). `dashboard.html` queda solo markup + CSS +
  `<script src="/static/dashboard.js">`. Datasette ya sirve `/static/` (`--static
  static:/app/static`) y oauth2-proxy lo tiene en la allow-list pública; no hizo falta
  tocar config. Verificado en vivo: `/` referencia el JS y `/static/dashboard.js` → 200.
