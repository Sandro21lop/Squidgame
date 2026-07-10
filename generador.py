#!/usr/bin/env python3
"""
generador.py — Generador de licencias standalone, sin necesidad de levantar
Flask ni tocar la base de datos. Para uso personal desde la terminal.

Usa exactamente la misma lógica que license_generator.py (mismo formato de
clave, mismo cifrado AES-GCM con tu SECRET_KEY), así que cualquier clave que
generes acá el backend la va a reconocer sin problema.

IMPORTANTE: lee SECRET_KEY de tu archivo .env (la misma que usa app.py). Si
generás claves con una SECRET_KEY distinta a la del backend en producción,
esas claves NO se van a poder validar ahí — usá siempre la misma.

Uso
───
  # Modo interactivo (te va preguntando)
  python generador.py

  # Directo por argumentos
  python generador.py nuevo --tiktok fulanito --plan mensual
  python generador.py nuevo --tiktok fulanito --plan mensual --email cliente@correo.com

  # Decodificar una clave existente (ver a quién pertenece, plan, fechas)
  python generador.py decodificar QGT-MEN-XXXXX-XXXXX-...

  # Listar planes disponibles
  python generador.py planes
"""
import argparse
import os
import sys

# Aseguramos poder importar license_generator.py aunque se corra el script
# desde otra carpeta.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from license_generator import (  # noqa: E402
    PLANES,
    generar_licencia,
    decodificar_licencia,
    normalizar_tiktok,
)


def _secret_key() -> str:
    secret = os.environ.get("SECRET_KEY")
    if not secret or secret.startswith("dev-secret") or secret.startswith("cambia-esto"):
        print(
            "⚠️  No encontré una SECRET_KEY real en tu .env (o sigue con el "
            "valor de ejemplo).\n"
            "   Poné en tu .env: SECRET_KEY=algo-largo-y-aleatorio\n"
            "   y usá SIEMPRE la misma que tiene el backend en producción,\n"
            "   o las claves que generes acá no van a validar ahí.",
            file=sys.stderr,
        )
        sys.exit(1)
    return secret


def cmd_nuevo(args):
    secret = _secret_key()
    tiktok = args.tiktok or input("Usuario de TikTok del comprador: ").strip()

    plan = args.plan
    if not plan:
        print("Planes disponibles:")
        for clave, datos in PLANES.items():
            print(f"  - {clave}: {datos['nombre']} (${datos['precio']}, {datos['dias']} días)")
        plan = input("Plan: ").strip()

    try:
        clave, expira = generar_licencia(tiktok, plan, secret)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    print("\n✅ Licencia generada")
    print(f"   TikTok:   {normalizar_tiktok(tiktok)}")
    print(f"   Plan:     {plan}")
    print(f"   Expira:   {expira:%Y-%m-%d %H:%M} UTC")
    print(f"   Clave:    {clave}")

    if args.email:
        print(f"\n(No se envió correo automático — mandale esta clave manualmente a {args.email})")


def cmd_decodificar(args):
    secret = _secret_key()
    resultado = decodificar_licencia(args.clave, secret)

    if not resultado["valida"]:
        print(f"❌ {resultado['error']}", file=sys.stderr)
        sys.exit(1)

    print("✅ Clave válida")
    print(f"   TikTok:   {resultado['tiktok_username']}")
    print(f"   Plan:     {resultado['plan']}")
    print(f"   Emitida:  {resultado['emitida']:%Y-%m-%d %H:%M} UTC")
    print(f"   Expira:   {resultado['expira']:%Y-%m-%d %H:%M} UTC")
    print(f"   Vencida:  {'sí' if resultado['vencida'] else 'no'}")


def cmd_planes(_args):
    print("Planes definidos en license_generator.py:")
    for clave, datos in PLANES.items():
        print(f"  - {clave}: {datos['nombre']} — ${datos['precio']} / {datos['dias']} días")


def main():
    parser = argparse.ArgumentParser(description="Generador de licencias standalone")
    sub = parser.add_subparsers(dest="comando")

    p_nuevo = sub.add_parser("nuevo", help="Generar una licencia nueva")
    p_nuevo.add_argument("--tiktok", help="Usuario de TikTok del comprador")
    p_nuevo.add_argument("--plan", choices=list(PLANES.keys()), help="Plan a asignar")
    p_nuevo.add_argument("--email", help="Solo referencia, no envía correo (eso lo hace el backend)")
    p_nuevo.set_defaults(func=cmd_nuevo)

    p_dec = sub.add_parser("decodificar", help="Ver el contenido de una clave existente")
    p_dec.add_argument("clave", help="La clave completa, ej: QGT-MEN-XXXXX-...")
    p_dec.set_defaults(func=cmd_decodificar)

    p_planes = sub.add_parser("planes", help="Listar los planes disponibles")
    p_planes.set_defaults(func=cmd_planes)

    args = parser.parse_args()

    if not args.comando:
        # Modo interactivo simple si se corre sin subcomando
        print("¿Qué querés hacer?")
        print("  1) Generar una licencia nueva")
        print("  2) Decodificar una clave existente")
        opcion = input("Opción [1/2]: ").strip()
        if opcion == "2":
            clave = input("Clave a decodificar: ").strip()
            cmd_decodificar(argparse.Namespace(clave=clave))
        else:
            cmd_nuevo(argparse.Namespace(tiktok=None, plan=None, email=None))
        return

    args.func(args)


if __name__ == "__main__":
    main()
