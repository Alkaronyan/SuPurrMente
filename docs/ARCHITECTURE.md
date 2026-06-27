# Arquitectura — SuPurrMente

Estado real del sistema (V1). Para el *porqué* de las decisiones, ver
[CONTEXT.md](CONTEXT.md) y los [logs de sesión](sessions/).

## Stack

| Componente | Tecnología |
|---|---|
| Fuente de datos | `pylitterbot` (API no oficial de Whisker, LR4) |
| Lenguaje | Python 3.11 |
| Almacenamiento primario | SQLite (`/data/weights.db`) |
| Backup | CSV (`/data/weights.csv`), mismo volumen |
| Visualización | Datasette + Chart.js (puerto 8001) |
| Notificaciones | Gmail SMTP (App Password) |
| Programación | cron dentro del contenedor (cada 6h) |
| Despliegue | Docker Compose en Raspberry Pi 4; datos en NAS Synology vía NFS |

La Synology DS214+ (ARMv7 32-bit) es **solo servidor de ficheros** (NFS). Todo el
cómputo corre en la Raspi.

## Flujo de datos (cada ciclo de cron)

```
fetcher → [api_contract + version log] → classifier (validación) →
SQLiteStore + CsvStore → HealthChecker + robot_health → EmailSender
```

1. **fetcher** lee de `account.pets[*].weight_history` (peso por gato, **en libras**
   → kg), convierte a hora local Madrid, y de paso recoge `get_insight` (ciclos/día)
   y estado del robot (arena, cajón, online). Valida el contrato de la API.
2. **classifier** ya no clasifica datos en vivo (la API da el gato); solo valida y
   actualiza la media móvil. Sigue clasificando de verdad en la migración histórica.
3. **storage** escribe a SQLite (primario) y CSV (backup), ambos dedup por timestamp.
4. **alertas** evalúa salud por gato + estado del robot, con cooldown de 24h.

## Módulos (`app/src/`)

| Módulo | Rol |
|---|---|
| `main.py` | Orquesta el pipeline en cada tick |
| `fetcher.py` | API → `FetchResult` (visitas + issues de contrato + versiones + datos del robot) |
| `api_contract.py` | Valida que la API sigue dando los datos esperados (sin importar pylitterbot, testeable) |
| `classifier.py` | Umbral dinámico; `classify_known` valida el gato de la API |
| `timeutils.py` | Única fuente de verdad de zona horaria (Europe/Madrid) |
| `storage/sqlite_store.py` | Primario; tablas `visits`, `sent_alerts`, `api_meta`, `box_usage`, `robot_snapshots` |
| `storage/csv_store.py` | Backup en NAS, append + dedup |
| `alerts/health.py` | Anomalías de peso, tendencia, ausencia, pico de visitas (por gato) |
| `alerts/robot_health.py` | Arena baja, cajón lleno, robot offline (cat='caja') |
| `alerts/email_sender.py` | Agrupa las alertas de un ciclo en un email |
| `migrate.py` | Una vez: ingiere `deprecated/*.csv` → SQLite + CSV |

## Datos almacenados (SQLite)

- `visits` — lecturas de peso por gato (cada lectura = una visita). UNIQUE(timestamp).
- `sent_alerts` — huellas de alertas enviadas (dedup por cooldown).
- `api_meta` — una fila por *cambio* de firmware/versión de librería.
- `box_usage` — ciclos de limpieza por día (total del robot); se acumula con el tiempo.
- `robot_snapshots` — nivel de arena/cajón + estado online por ciclo.

**Zona horaria:** todo se guarda y muestra en hora local Madrid. La API (UTC) se
convierte; el CSV ya es local. Detalle en `timeutils.py`.

## Backup

El "backup" es el CSV (`/data/weights.csv`), que vive en el **mismo volumen** que la
BD. En producción `/data` es el **montaje NFS → Synology NAS**
(`/mnt/nas/cat-weights:/data`); no hay sincronización aparte ni OneDrive — es un
volumen montado, así que cada escritura va directa al NAS. (En la Raspi requiere el
montaje NFS, que `setup.sh` comprueba.)

El CSV es **auto-descriptivo y versionado por API**: cada fichero empieza con
cabeceras `# api_version: ...` / `# created: ...`. Cuando cambia la versión de la API
de Whisker, `csv_store` archiva el fichero activo y abre uno nuevo, de modo que cada
fichero contiene una sola era de API. Así, si Whisker vuelve a cambiar el formato del
volcado (ya pasó), el cambio de parser/formato queda contenido en un fichero nuevo en
vez de mezclar esquemas — y el email de alerta de cambio de API es la señal para ir a
inspeccionar el nuevo formato y adaptar el parser.

## Clasificador

Peso estimado de cada gato = media móvil de 14 días de sus muestras. Umbral = punto
medio entre ambas medias, recalculado en cada visita. Semillas: Pirata 6.6 / Robin
4.4 kg. En datos en vivo la API da el gato, así que el clasificador solo **valida**
(avisa si el peso contradice al gato que dice la API). En la migración histórica
(sin gato) sí clasifica.

## Resiliencia ante cambios de la API

La API no oficial ya cambió una vez. En cada ciclo se valida el contrato y se
registra la versión del firmware/librería; cualquier desviación dispara un email.
Ver `api_contract.py` y la tabla `api_meta`.

## Configuración

`app/config.yml` controla todos los parámetros: semillas, ventana de media móvil,
umbrales de salud (±2σ/30d, tendencia 5d, ausencia 24h, pico 4 visitas/6h), cron
(`0 */6 * * *`), cooldown de alertas (24h), tolerancias de migración, rangos
plausibles de la API, umbrales de arena/cajón. Los emails se leen de `FROM_EMAIL`
/ `TO_EMAILS` en `.env`, **no** de `config.yml`.

## Formato de los CSV históricos (migración)

Exports de Whisker, columnas `Actividad, Marca de tiempo, Valor`. Solo filas
`"Peso de la mascota registrado"`. `migrate.py` autodetecta 4 formatos de fecha
(inglés 12h, español 12h con `a. m.`/`p. m.` y `\xa0`, europeo 24h, y `, a las`),
coma o punto decimal, y saca el año del nombre del fichero. Dedup difuso ±120s
contra lo ya almacenado (solape CSV↔API).

## Fuera de alcance

Home Assistant, Grafana (Datasette sirve el dashboard), despliegue cloud, correr
Docker en la Synology, push en tiempo real (existe `robot.subscribe()` pero no
compensa frente al polling cada 6h).
