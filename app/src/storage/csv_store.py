import csv
import logging
from pathlib import Path
from typing import Optional

import timeutils

log = logging.getLogger(__name__)

# Internal backup format — ISO timestamp (local Madrid wall-clock) + normalised
# fields, independent of the Whisker export format that migrate.py parses.
CSV_COLUMNS = ["timestamp", "cat", "weight_kg", "raw_weight_kg", "confidence"]
DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_META_PREFIX = "#"
_VERSION_KEY = "# api_version:"
_CREATED_KEY = "# created:"
_UNKNOWN = "desconocida"


class CsvStore:
    """Backup CSV, self-describing by Whisker API version.

    Each file starts with metadata comment lines recording the API version it was
    written under. When that version changes, the active file is archived and a new
    one opened, so each file holds a single API era. If Whisker ever changes the dump
    format/units again (it has before), the parser+format change is contained to a
    new file instead of mixing schemas — and the API-change email alert
    (api_contract / api_meta) is the cue to go inspect the new format.
    """

    def __init__(self, config: dict) -> None:
        self._path = Path(config["storage"]["csv_path"])

    def write(self, visits: list, api_version: Optional[str] = None) -> None:
        # Reconcile the active file's recorded API version before appending.
        if self._path.exists() and self._path.stat().st_size > 0:
            recorded = self._read_meta_version()
            if recorded is None:
                self._stamp_legacy(api_version)            # add header to old file
            elif recorded == _UNKNOWN and api_version:
                self._restamp_version(api_version)         # pin to first real version
            elif api_version is not None and recorded != api_version:
                self._rotate(recorded)                     # API changed → new file

        existing_timestamps = self._load_timestamps()

        new_rows = []
        for v in visits:
            ts = v.timestamp.strftime(DATE_FORMAT)
            if ts in existing_timestamps:
                continue
            new_rows.append({
                "timestamp": ts,
                "cat": v.cat,
                "weight_kg": v.weight_kg,
                "raw_weight_kg": v.raw_weight_kg,
                "confidence": round(v.confidence, 4),
            })

        if not new_rows:
            log.info("No new CSV rows (all timestamps already present)")
            return

        self._path.parent.mkdir(parents=True, exist_ok=True)
        fresh = not self._path.exists() or self._path.stat().st_size == 0

        with open(self._path, "a", newline="", encoding="utf-8") as f:
            if fresh:
                self._write_meta_header(f, api_version)
                csv.DictWriter(f, fieldnames=CSV_COLUMNS).writeheader()
            csv.DictWriter(f, fieldnames=CSV_COLUMNS).writerows(new_rows)

        log.info("Wrote %d row(s) to CSV at %s", len(new_rows), self._path)

    # ── metadata header ───────────────────────────────────────────────────────
    def _write_meta_header(self, f, api_version: Optional[str]) -> None:
        f.write("# SuPurrMente backup CSV\n")
        f.write(f"{_VERSION_KEY} {api_version or _UNKNOWN}\n")
        f.write(f"{_CREATED_KEY} {timeutils.now().strftime(DATE_FORMAT)}\n")

    def _read_meta_version(self) -> Optional[str]:
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                if line.startswith(_VERSION_KEY):
                    return line[len(_VERSION_KEY):].strip()
                if not line.startswith(_META_PREFIX):
                    return None  # data started without a version line → legacy
        return None

    def _stamp_legacy(self, api_version: Optional[str]) -> None:
        """Prepend a metadata header to a pre-versioning file, in place."""
        content = self._path.read_text(encoding="utf-8")
        with open(self._path, "w", newline="", encoding="utf-8") as f:
            self._write_meta_header(f, api_version)
            f.write(content)
        log.info("CSV legacy sellado con api_version=%s", api_version or _UNKNOWN)

    def _restamp_version(self, api_version: str) -> None:
        """Replace the recorded version in place (no rotation) — used to pin an
        'unknown' header (e.g. from migration) to the first real API version."""
        lines = self._path.read_text(encoding="utf-8").splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.startswith(_VERSION_KEY):
                lines[i] = f"{_VERSION_KEY} {api_version}\n"
                break
        self._path.write_text("".join(lines), encoding="utf-8")
        log.info("CSV api_version fijada a %s", api_version)

    def _rotate(self, old_version: str) -> None:
        close = timeutils.now().strftime("%Y%m%d-%H%M%S")
        archive = self._path.with_name(f"{self._path.stem}_{close}{self._path.suffix}")
        self._path.replace(archive)  # active file no longer exists → next write is fresh
        log.info("CSV rotado por cambio de API (era %s). Archivado en %s", old_version, archive.name)

    def _load_timestamps(self) -> set[str]:
        if not self._path.exists():
            return set()
        with open(self._path, encoding="utf-8") as f:
            data_lines = [ln for ln in f if not ln.startswith(_META_PREFIX)]
        return {row["timestamp"] for row in csv.DictReader(data_lines)}
