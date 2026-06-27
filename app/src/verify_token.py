"""
Diagnóstico: ¿el token de Whisker está guardado y es USABLE de verdad?

Carga el token, dice si toca refrescarlo y **prueba una conexión en vivo** contra
Whisker (lista gatos y robots). Si esto funciona, el ciclo de datos también.

Uso:  docker compose exec -u tracker supurrmente python src/verify_token.py
"""
import asyncio

from main import load_config
import whisker_auth


async def _run():
    cfg = load_config()
    tok = whisker_auth.load_token(cfg)
    if not tok:
        print("✗ No hay token guardado en", whisker_auth.token_path(cfg))
        print("  Inicia sesión en /whisker-login.")
        return

    print("✓ Token presente:", ", ".join(sorted(tok)))
    print("  ¿toca refrescar (media vida)?:", whisker_auth.needs_refresh(tok))
    print("  Probando conexión en vivo con Whisker…")

    account = await whisker_auth.connect_with_token(cfg, load_robots=True, load_pets=True)
    try:
        print("  ✓ Autenticado.")
        print("    Gatos :", [p.name for p in account.pets])
        print("    Robots:", [getattr(r, "serial", "?") for r in account.robots])
    finally:
        await account.disconnect()


if __name__ == "__main__":
    asyncio.run(_run())
