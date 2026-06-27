"""Crea el esquema SQLite si no existe.

Datasette no arranca contra una BD inexistente; el entrypoint ejecuta esto (como el
usuario 'tracker') antes de levantar los servicios, para que el dashboard esté vivo
aunque todavía no haya datos.
"""
from main import load_config
from storage.sqlite_store import SQLiteStore

if __name__ == "__main__":
    SQLiteStore(load_config())  # __init__ ejecuta los CREATE TABLE IF NOT EXISTS
    print("Esquema SQLite listo")
