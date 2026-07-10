"""
Wrapper delgado sobre la API de Lemon Squeezy.

Dos tipos de llamadas:
1. API de licencias (activate/validate/deactivate) — son endpoints PÚBLICOS,
   pensados para ser llamados por la app del cliente final (o por nuestro
   backend, que es lo que hacemos aquí para poder añadir nuestra propia capa
   de control). No requieren API key.
2. API general (v1/*) — requiere el API key de tu cuenta (Bearer token).
   La usamos para leer/gestionar suscripciones y verificar firmas de webhook.
"""
import hashlib
import hmac
import requests

LS_LICENSE_API = "https://api.lemonsqueezy.com/v1/licenses"
LS_API = "https://api.lemonsqueezy.com/v1"


class LemonSqueezyError(Exception):
    pass


def _headers(api_key):
    return {
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
        "Authorization": f"Bearer {api_key}",
    }


def verify_webhook_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    """Verifica que el webhook realmente venga de Lemon Squeezy (HMAC-SHA256)."""
    if not secret or not signature_header:
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(digest, signature_header)
    except Exception:
        return False


def activate_license(license_key: str, instance_name: str) -> dict:
    """Activa una license key para una máquina/instancia concreta.
    Lemon Squeezy controla el activation_limit automáticamente:
    si ya se alcanzó el límite, devuelve activated=False.
    """
    resp = requests.post(
        f"{LS_LICENSE_API}/activate",
        data={"license_key": license_key, "instance_name": instance_name},
        timeout=10,
    )
    return resp.json()


def validate_license(license_key: str, instance_id: str | None = None) -> dict:
    data = {"license_key": license_key}
    if instance_id:
        data["instance_id"] = instance_id
    resp = requests.post(f"{LS_LICENSE_API}/validate", data=data, timeout=10)
    return resp.json()


def deactivate_license(license_key: str, instance_id: str) -> dict:
    resp = requests.post(
        f"{LS_LICENSE_API}/deactivate",
        data={"license_key": license_key, "instance_id": instance_id},
        timeout=10,
    )
    return resp.json()


def crear_checkout(
    api_key: str,
    store_id: str,
    variant_id: str,
    tiktok_username: str,
    redirect_url: str,
    email=None,
) -> str:
    """Crea un checkout de Lemon Squeezy vía API para un plan (variant) concreto,
    con el usuario de TikTok metido en checkout_data.custom. Ese custom data
    vuelve intacto en el webhook (meta.custom_data) cuando se confirme el pago,
    así el webhook sabe para quién generar la licencia.

    Se usa la API en vez de un link estático con query params porque los
    checkouts creados por API no aceptan prefill por URL (Lemon Squeezy
    responde "invalid signature"); hay que pasar los datos al crearlo.

    Devuelve la URL del checkout, lista para redirigir al comprador.
    """
    body = {
        "data": {
            "type": "checkouts",
            "attributes": {
                "product_options": {
                    "redirect_url": redirect_url,
                },
                "checkout_data": {
                    "custom": {"tiktok_username": tiktok_username},
                    **({"email": email} if email else {}),
                },
            },
            "relationships": {
                "store": {"data": {"type": "stores", "id": str(store_id)}},
                "variant": {"data": {"type": "variants", "id": str(variant_id)}},
            },
        }
    }
    resp = requests.post(
        f"{LS_API}/checkouts", headers=_headers(api_key), json=body, timeout=10
    )
    if resp.status_code not in (200, 201):
        raise LemonSqueezyError(resp.text)

    return resp.json()["data"]["attributes"]["url"]


def get_subscription(api_key: str, subscription_id: str) -> dict:
    resp = requests.get(
        f"{LS_API}/subscriptions/{subscription_id}", headers=_headers(api_key), timeout=10
    )
    if resp.status_code != 200:
        raise LemonSqueezyError(resp.text)
    return resp.json()


def cancel_subscription(api_key: str, subscription_id: str) -> dict:
    resp = requests.delete(
        f"{LS_API}/subscriptions/{subscription_id}", headers=_headers(api_key), timeout=10
    )
    if resp.status_code not in (200, 204):
        raise LemonSqueezyError(resp.text)
    return resp.json() if resp.text else {}
