"""
licencia.py — Módulo de licencia para Quid Game TikTok.

Cómo integrarlo en tu juego (main.py):

    from licencia import verificar_licencia

    if not verificar_licencia():
        sys.exit(0)   # el propio módulo ya mostró el mensaje al usuario

    # ... arranca pygame normalmente aquí abajo ...

Qué hace:
1. La primera vez que se ejecuta, pide la clave de licencia (ventana simple,
   sin consola) y la activa contra tu backend.
2. La guarda en un archivo local junto al ejecutable (licencia_local.json).
3. En cada arranque, valida contra el backend. Si el server no responde
   (sin internet un momento, o caído), deja seguir usando el juego durante
   unos días de gracia usando la última validación exitosa que se guardó
   localmente — así no se corta el stream en pleno directo por un problema
   de red.
"""
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta

import requests

# ⚠️ Cambia esto por la URL real de tu servidor cuando lo despliegues
BASE_URL = "https://TU-DOMINIO.com"

RUTA_CONFIG = os.path.join(
    os.path.dirname(os.path.abspath(sys.argv[0])), "licencia_local.json"
)

DIAS_GRACIA_SIN_INTERNET = 3


def _nombre_de_equipo():
    return f"{os.environ.get('COMPUTERNAME', 'pc')}-{uuid.getnode()}"


def _leer_config():
    if os.path.exists(RUTA_CONFIG):
        try:
            with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _guardar_config(data):
    with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _pedir_clave_al_usuario():
    """Ventana simple para pedir la clave, sin depender de que haya consola
    (funciona igual en un .exe empaquetado con --windowed)."""
    try:
        import tkinter as tk
        from tkinter import simpledialog, messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            "Quid Game TikTok — Activación",
            "Ingresa la clave de licencia que recibiste al comprar Quid Game TikTok.",
        )
        clave = simpledialog.askstring("Quid Game TikTok — Activación", "Clave de licencia:")
        root.destroy()
        return (clave or "").strip()
    except Exception:
        # Fallback si tkinter no está disponible: pide por consola
        return input("Ingresa tu clave de licencia de Quid Game TikTok: ").strip()


def _mostrar_error(mensaje):
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Quid Game TikTok — Licencia", mensaje)
        root.destroy()
    except Exception:
        print(f"[LICENCIA] {mensaje}")


def verificar_licencia() -> bool:
    """Punto de entrada único. Devuelve True si el juego puede arrancar."""
    config = _leer_config()
    license_key = config.get("license_key")
    instance_id = config.get("instance_id")

    # ── Primera activación ──────────────────────────────
    if not license_key:
        license_key = _pedir_clave_al_usuario()
        if not license_key:
            _mostrar_error("No ingresaste una clave. El juego no puede continuar.")
            return False

        try:
            resp = requests.post(
                f"{BASE_URL}/api/activate",
                json={"license_key": license_key, "instance_name": _nombre_de_equipo()},
                timeout=12,
            )
            data = resp.json()
        except Exception:
            _mostrar_error(
                "No se pudo conectar al servidor de licencias. Revisa tu internet e intenta de nuevo."
            )
            return False

        if not data.get("ok"):
            _mostrar_error(data.get("mensaje", "Clave inválida."))
            return False

        config = {
            "license_key": license_key,
            "instance_id": data.get("instance_id"),
            "ultima_validacion_ok": datetime.utcnow().isoformat(),
        }
        _guardar_config(config)
        return True

    # ── Validación en arranques posteriores ─────────────
    try:
        resp = requests.post(
            f"{BASE_URL}/api/validate",
            json={"license_key": license_key, "instance_id": instance_id},
            timeout=12,
        )
        data = resp.json()
    except Exception:
        # Sin internet / servidor caído: usa el período de gracia local
        ultima = config.get("ultima_validacion_ok")
        if ultima:
            fecha = datetime.fromisoformat(ultima)
            if datetime.utcnow() <= fecha + timedelta(days=DIAS_GRACIA_SIN_INTERNET):
                return True
        _mostrar_error(
            "No se pudo verificar tu licencia y se agotó el período de gracia sin internet. "
            "Conéctate e intenta de nuevo."
        )
        return False

    if not data.get("ok"):
        _mostrar_error(data.get("mensaje", "Tu licencia no está activa."))
        return False

    config["ultima_validacion_ok"] = datetime.utcnow().isoformat()
    _guardar_config(config)
    return True
