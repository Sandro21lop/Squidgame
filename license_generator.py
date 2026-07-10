"""
license_generator.py — Generador y verificador de licencias de Quid Game TikTok.

Cómo funciona
─────────────
Cada clave de licencia lleva ADENTRO, cifrado con tu SECRET_KEY, el usuario
de TikTok del comprador y el plan que pagó. No es un ID suelto en una base
de datos: la clave misma "sabe" de quién es. Ventajas prácticas para ti:

  - Si alguien te escribe con una clave y nada más, puedes descifrarla y
    saber al instante a qué cuenta de TikTok pertenece (soporte rápido).
  - Si ves la misma clave activándose en streams de cuentas de TikTok
    distintas, es señal de reventa/compartir — puedes bloquearla desde el panel.
  - El formato es independiente de la pasarela de pago: hoy la generas a
    mano desde el panel admin, mañana la genera sola un webhook de Lemon
    Squeezy / Stripe / lo que sea, sin cambiar nada de esto.

Formato de la clave: QGT-<PLAN>-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX
  QGT   = Quid Game TikTok
  PLAN  = MEN (mensual) / SEM (6 meses) / ANU (1 año)
  resto = payload binario cifrado (AES-GCM) en base32, corto a propósito
          para que se pueda copiar/pegar sin dramas.
"""
import base64
import os
import struct
from datetime import datetime, timedelta, timezone

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ── Planes disponibles ──────────────────────────────────────────────
# "dias" define cuánto dura cada licencia. Si cambias precios, solo
# tocas esto — la landing y el panel admin leen de aquí.
# Un solo plan por ahora: $5/mes. El formato de clave ya soporta más
# planes si algún día quieres agregar uno (deja el diccionario, no lo
# vuelvas una sola variable) — solo agrega la entrada aquí y en
# _PREFIJO_PLAN / _CODIGO_PLAN.
PLANES = {
    "mensual": {"nombre": "Mensual", "dias": 30, "precio": 5},
}

_PREFIJO_PLAN = {"mensual": "MEN", "semestral": "SEM", "anual": "ANU"}
_CODIGO_PLAN = {"mensual": 1, "semestral": 2, "anual": 3}
_PLAN_DESDE_CODIGO = {v: k for k, v in _CODIGO_PLAN.items()}
_PLAN_DESDE_PREFIJO = {v: k for k, v in _PREFIJO_PLAN.items()}

_SALT_KDF = b"quid-game-tiktok-licencias-v1"
_AAD = b"QGT-v1"


def _clave_aes(secret_key: str) -> bytes:
    """Deriva una clave AES-256 estable a partir de tu SECRET_KEY de Flask,
    para no tener que guardar otra clave secreta aparte."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=_SALT_KDF, iterations=390_000
    )
    return kdf.derive(secret_key.encode("utf-8"))


def normalizar_tiktok(usuario: str) -> str:
    return (usuario or "").strip().lstrip("@").lower()


def generar_licencia(tiktok_username: str, plan: str, secret_key: str):
    """Crea una clave nueva. Devuelve (clave, fecha_expira)."""
    if plan not in PLANES:
        raise ValueError(f"Plan desconocido: {plan}")

    usuario = normalizar_tiktok(tiktok_username)
    if not usuario:
        raise ValueError("Falta el usuario de TikTok.")
    usuario_bytes = usuario.encode("utf-8")
    if len(usuario_bytes) > 60:
        raise ValueError("El usuario de TikTok es demasiado largo.")

    ahora_aware = datetime.now(timezone.utc).replace(microsecond=0)
    expira_aware = ahora_aware + timedelta(days=PLANES[plan]["dias"])
    ahora = ahora_aware.replace(tzinfo=None)
    expira = expira_aware.replace(tzinfo=None)

    # payload binario compacto: [len_usuario(1)][usuario][plan(1)][iat(4)][exp(4)]
    payload = struct.pack(
        f">B{len(usuario_bytes)}sBII",
        len(usuario_bytes),
        usuario_bytes,
        _CODIGO_PLAN[plan],
        int(ahora_aware.timestamp()),
        int(expira_aware.timestamp()),
    )

    nonce = os.urandom(12)
    ciphertext = AESGCM(_clave_aes(secret_key)).encrypt(nonce, payload, _AAD)
    crudo = nonce + ciphertext

    cuerpo = base64.b32encode(crudo).decode("utf-8").rstrip("=")
    bloques = [cuerpo[i:i + 5] for i in range(0, len(cuerpo), 5)]
    clave = f"QGT-{_PREFIJO_PLAN[plan]}-" + "-".join(bloques)
    return clave, expira


def decodificar_licencia(license_key: str, secret_key: str) -> dict:
    """Descifra una clave y devuelve lo que lleva adentro. No consulta la
    base de datos: es una verificación puramente criptográfica de que la
    clave es auténtica (la emitiste tú) y de qué contiene."""
    license_key = (license_key or "").strip().upper()
    partes = license_key.split("-")

    if len(partes) < 3 or partes[0] != "QGT" or partes[1] not in _PLAN_DESDE_PREFIJO:
        return {"valida": False, "error": "Formato de clave no reconocido."}

    cuerpo = "".join(partes[2:])
    relleno = "=" * (-len(cuerpo) % 8)

    try:
        crudo = base64.b32decode(cuerpo + relleno)
        nonce, ciphertext = crudo[:12], crudo[12:]
        payload = AESGCM(_clave_aes(secret_key)).decrypt(nonce, ciphertext, _AAD)

        len_usuario = payload[0]
        usuario = payload[1:1 + len_usuario].decode("utf-8")
        resto = payload[1 + len_usuario:]
        plan_codigo, iat_ts, exp_ts = struct.unpack(">BII", resto)
    except InvalidTag:
        return {"valida": False, "error": "Clave inválida o alterada."}
    except Exception:
        return {"valida": False, "error": "No se pudo leer la clave."}

    plan = _PLAN_DESDE_CODIGO.get(plan_codigo, "desconocido")
    expira = datetime.fromtimestamp(exp_ts, tz=timezone.utc).replace(tzinfo=None)
    emitida = datetime.fromtimestamp(iat_ts, tz=timezone.utc).replace(tzinfo=None)
    return {
        "valida": True,
        "tiktok_username": usuario,
        "plan": plan,
        "emitida": emitida,
        "expira": expira,
        "vencida": datetime.utcnow() > expira,
    }
