# Contexto y motivación — SuPurrMente

## Qué es

Sistema auto-alojado para extraer el peso de una Litter-Robot 4, clasificar cada
medida por gato, almacenarla a largo plazo y enviar alertas de salud por email.

## Por qué

La app de Whisker solo guarda **1 semana** de histórico. Este sistema da
almacenamiento indefinido, clasificación por gato y alertas clínicamente útiles
(tendencias de peso, ausencias, picos de frecuencia). Ambos gatos están marcados
con **FeLV** en la API — vigilar el peso importa de verdad.

- Gatos: **Pirata** (~6.6 kg) y **Robin** (~4.4 kg).
- Hardware: Litter-Robot 4 conectada a la nube de Whisker.

## Decisiones clave y su razón

- **Umbral dinámico, no fijo.** Un umbral fijo se degrada cuando los gatos cambian
  de peso; la media móvil se adapta sola. (En vivo la API ya da el gato, así que el
  clasificador quedó como validación — ver [logs](sessions/).)
- **Nunca clasificar mal en silencio.** Si la confianza cae, se avisa. Como red
  secundaria, `crosscheck.py` contrasta cada lectura con la tendencia reciente del
  gato que da la API y avisa por email si discrepan (sin reasignar: la API manda).
- **Alertas como feature central**, no añadido: son señales clínicas.
- **Email only** (Gmail SMTP). Sin Home Assistant, Telegram ni push: simplicidad y
  cero dependencias externas.
- **SQLite + CSV** en un volumen montado del NAS (NFS). El NAS es solo servidor de
  ficheros. Dedup por timestamp en cada escritura.
- **Idempotencia de todo el sistema**: reejecutar cualquier paso, incluso tras un
  fallo, converge al mismo estado.
- **Infra: Raspberry Pi 4.** La Synology DS214+ (ARMv7 32-bit) se descartó para
  cómputo; sirve solo como almacenamiento NFS. Mover a producción = copiar la
  carpeta a la Raspi y `docker compose up`.

## Decisiones que cambiaron durante la construcción

- **InfluxDB → SQLite**: con ~4 visitas/día no se justificaba el time-series.
- **El clasificador pasó de motor principal a validación**: la API resultó dar el
  gato directamente (cada `Pet` con su `weight_history`).
- **4 contenedores → 1 contenedor** (uso personal): se prioriza el **aislamiento por
  usuario** (un UID por proceso + secretos 600) sobre la separación por contenedor. El
  proceso de cara a internet (oauth2-proxy) no puede leer las credenciales del tracker.
- **Whisker: contraseña → token.** El password ya no se guarda en disco; un formulario
  web (tras login Google) emite un **token revocable** que se refresca solo.
- **cron → APScheduler** (dentro del proceso web del tracker), manteniendo la idempotencia.
- **Acceso web con Google.** El dashboard es público; el explorador de la BD y la
  configuración van tras oauth2-proxy restringido a `@gonzalez.team`.

## Fuera de alcance

Home Assistant, Grafana, modificar la app/firmware de Whisker, despliegue cloud,
Docker en la Synology.
