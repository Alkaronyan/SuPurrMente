# Sesión 2026-06-27 — Datos reales, resiliencia y V1

Del sistema "construido pero sin datos" a **V1 con datos reales, idempotente y
resistente a cambios de la API**. Es la sesión donde se descubrió cómo funciona de
verdad la API de la LR4 y se corrigieron varios bugs serios.

## 1. Idempotencia de todo el sistema

Requisito del usuario: reejecutar cualquier cosa (un ciclo, una migración, una
evaluación de alertas), incluso tras un fallo a mitad, debe converger al mismo
estado. Implementado/verificado:

- SQLite: `INSERT OR IGNORE` sobre `timestamp UNIQUE` (gana la primera escritura).
- CSV (= backup NAS): dedup por set de timestamps.
- Migración: `Path.replace` (no `.rename`, que crashea en Windows si el destino
  existe); un archivo con >5% de filas no parseadas **no se archiva** (no se
  pierden datos en silencio); dedup difuso ±120s contra lo ya almacenado.
- Alertas: tabla `sent_alerts` + `Alert.fingerprint()` (cat+kind) con cooldown de
  24h → una condición en curso manda **un** email/día, no uno por ciclo.
- Tests en `tests/test_idempotency.py` que bloquean estas garantías.

## 2. Bugs del parser de migración

- **`\xa0` (espacio de no separación)** en el export español de junio 2025
  (`6/21 7:30p.\xa0m.`) → se detectaba como formato C y se perdían ~218 filas en
  silencio. Fix: `_normalize_spaces`.
- **Formato `, a las`** del export de junio 2026 (`26/6, a las 8:16`) → europeo 24h
  con `, a las` insertado. Fix: se quita con regex antes de parsear.
- Recuperados mayo (0→49) y junio 2025 (7→176).

## 3. La API real (el gran descubrimiento)

El `fetcher` original estaba **fundamentalmente equivocado**: leía `entry.weight`
de `robot.get_activity_history()`, que **no existe** (ese histórico solo tiene
ciclos de limpieza y nivel de arena). Tras inspeccionar la API real:

- Los pesos viven en **`account.pets[*].weight_history`** (lista de
  `WeightMeasurement(timestamp, weight)`), y **en LIBRAS** (×0.453592). Robin
  9.67 lb → 4.39 kg ✓, Pirata 14.6 lb → 6.62 kg ✓.
- **La API ya identifica al gato** (cada `Pet` tiene su propio historial). Resuelto
  el gran "¿hay ID por gato?": sí. El clasificador pasa a **validación**
  (`classify_known`); el de umbral dinámico sigue usándose solo en la migración
  histórica (que no trae gato).
- La API solo guarda ~1 semana → el cron es lo que construye el histórico largo.
- `get_insight()` da **30+ días** de ciclos de limpieza diarios (más que el
  weight_history), pero los ciclos **no** mapean 1:1 con visitas por gato → no se
  pueden atribuir a un gato.

Datos de versión registrados (baseline): firmware
`ESP: 1.1.75 / PIC: 10512.3072.2.93 / TOF: 5.0.2.1`, pylitterbot `2025.5.0`,
serial `LR4C428620`, modelo `Litter-Robot 4`.

Scripts de diagnóstico que revelaron todo esto: `app/scripts/inspect_*.py`.

## 4. Bug del cron (no llegaban datos nuevos)

El cron fallaba en silencio cada hora con `python: not found`: cron arranca con un
PATH mínimo que excluye `/usr/local/bin`, **y no hereda** las variables de entorno
del contenedor (las credenciales). `entrypoint.sh` ahora inyecta PATH + secretos en
el crontab. Cron pasó de cada hora a **cada 6h** (4×/día, para que las alertas de
pérdida de peso lleguen a tiempo).

## 5. Detección de cambios de API + registro de versión

La API no oficial ya cambió una vez; puede volver a hacerlo. Cada ciclo:
`api_contract.validate()` comprueba que los datos llegan con la forma esperada
(mascotas presentes, gatos esperados, historial válido, y **cambio de unidad** vía
mediana/semilla por gato — detecta una regresión a libras en ambos gatos). Cualquier
fallo → **email crítico**. `record_api_meta()` registra firmware/versión y avisa al
cambiar. Tablas: `api_meta`.

## 6. Zona horaria → local Madrid + rebuild

El histórico (CSV) estaba en hora local etiquetada como UTC; la API daba UTC real →
desfase ~2h y duplicados en la semana de solape. Decisión del usuario: **todo a hora
local Madrid**. `src/timeutils.py` es la única fuente de verdad (`now`, `to_local`).
BD reconstruida desde cero (wipe → fetch API → migrar CSV con dedup) → ~2032 visitas
sin duplicados. Añadido `tzdata` a requirements.

## 7. Datos extra del robot

- **`box_usage`**: ciclos de limpieza por día (de `get_insight`), se acumula.
- **`robot_snapshots`**: litter_level, waste_drawer_level, is_online, last_seen por
  ciclo.
- **`robot_health`** alertas (cat='caja'): arena baja, cajón lleno, robot offline.

## 8. Dashboard

- **Frecuencia de visitas por gato** (barras/día) junto al peso. La frecuencia se
  deriva de la tabla `visits` (cada lectura = una visita).
- **3ª tarjeta "Caja"**: ciclos/día + estado (arena %, cajón %, online).

### Cambios de UI de otro agente (mismo día)

Documentados en su scratchpad e integrados:
- **Rotura de línea en huecos ≥4 días** (`insertGapNulls` + `spanGaps:false`) — un
  hueco de datos no se conecta de forma engañosa ni cae a cero.
- **Eje X temporal proporcional** (`type: 'time'` con `chartjs-adapter-date-fns`):
  un hueco de 1 mes ocupa visualmente un mes.
- **Subtítulos colapsables** (`toggleChart`) con flecha que rota al colapsar.
- Dejó el `#card-caja` estructural en el HTML; la lógica (`buildBoxChart` + query)
  se completó en esta sesión.

## 9. Backup CSV versionado por API

El backup es el CSV en el mismo volumen que la BD → en producción, NFS al NAS
Synology (no OneDrive, no sincronización aparte). Cada CSV es ahora auto-descriptivo:
empieza con `# api_version:` / `# created:`. Al detectar un cambio de versión de la
API, `csv_store` archiva el fichero activo y abre uno nuevo (una era de API por
fichero). Si Whisker cambia el formato del volcado otra vez, el cambio queda contenido
en un fichero nuevo; el email de alerta de cambio de API avisa para ir a inspeccionar
y adaptar el parser. Ficheros legacy sin cabecera se sellan en sitio; un header
'desconocida' (migración) se fija a la primera versión real sin rotar.

## 10. Reorganización para V1

`app/` (código, tests, static, Docker, config, deprecated), `docs/` (arquitectura,
contexto, estos logs), `scripts/` (ops) y `app/scripts/` (diagnóstico API). Borrado
el código muerto `storage/influx.py`. Docs principales simplificados.

## Estado al cierre

- **106 tests** en contenedor, verdes.
- Datos reales: ~2032 visitas (2025-01 → 2026-06), box_usage 31 días, snapshots.
- Cron cada 6h activo; API real funcionando; detección de cambios y registro de
  versión activos.
- Pendiente real: desplegar en la Raspberry Pi (`setup.sh`).
