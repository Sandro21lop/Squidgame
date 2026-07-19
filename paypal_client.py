"""
paypal_client.py — Wrapper delgado sobre la API REST de PayPal (Subscriptions).

Reemplaza a lemonsqueezy_client.py. Usamos "PayPal Subscriptions" (Billing
Plans) porque el negocio es igual que antes: planes recurrentes mensual /
semestral / anual, cada uno con su Plan ID de PayPal (algo como
"P-5ML4271244454362WXNWU5NQ") creado una vez desde el dashboard de PayPal
o vía API (ver crear_producto_y_planes.py / MIGRACION_PAYPAL.md).

Flujo:
1. El comprador pone su usuario de TikTok en /comprar.
2. crear_suscripcion() crea la suscripción en PayPal con ese usuario metido
   en `custom_id`, y devuelve la URL de aprobación (link "approve") a la
   que redirigimos al comprador para que confirme el pago en PayPal.
3. PayPal redirige de vuelta a /gracias tras la aprobación.
4. PayPal manda webhooks a /webhooks/paypal para BILLING.SUBSCRIPTION.ACTIVATED,
   PAYMENT.SALE.COMPLETED (cada cobro/renovación), BILLING.SUBSCRIPTION.CANCELLED,
   BILLING.SUBSCRIPTION.EXPIRED, BILLING.SUBSCRIPTION.SUSPENDED — y ahí es
   donde emitimos/renovamos/cancelamos la licencia, igual que hacíamos con
   Lemon Squeezy.

No hace falta ninguna librería nueva: solo `requests`, que ya estaba en
requirements.txt.
"""
import time

import requests

_PAYPAL_API = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com",
}

# Cache muy simple del access token en memoria de proceso (evita pedir uno
# nuevo en cada request; PayPal los da con ~9h de validez).
_token_cache = {"token": None, "expires_at": 0}


class PayPalError(Exception):
    pass


def _base_url(mode: str) -> str:
    return _PAYPAL_API.get(mode, _PAYPAL_API["sandbox"])


def get_access_token(client_id: str, client_secret: str, mode: str = "sandbox") -> str:
    """Pide (o reutiliza del cache) un OAuth2 access token client-credentials."""
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 30:
        return _token_cache["token"]

    resp = requests.post(
        f"{_base_url(mode)}/v1/oauth2/token",
        headers={"Accept": "application/json", "Accept-Language": "en_US"},
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=10,
    )
    if resp.status_code != 200:
        raise PayPalError(f"No se pudo obtener access token: {resp.text}")

    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + int(data.get("expires_in", 3000))
    return _token_cache["token"]


def _headers(client_id, client_secret, mode, extra=None):
    token = get_access_token(client_id, client_secret, mode)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if extra:
        headers.update(extra)
    return headers


def crear_suscripcion(
    client_id: str,
    client_secret: str,
    mode: str,
    plan_id: str,
    tiktok_username: str,
    return_url: str,
    cancel_url: str,
    email: str | None = None,
) -> dict:
    """Crea una suscripción en PayPal para un plan (plan_id) concreto, con
    el usuario de TikTok metido en `custom_id` (PayPal lo devuelve intacto
    en el `resource.custom_id` de cada webhook, así sabemos para quién
    generar/renovar la licencia).

    Devuelve el dict completo de PayPal; el caller normalmente solo
    necesita `id` (el subscription_id) y el link "approve" para redirigir
    al comprador.
    """
    body = {
        "plan_id": plan_id,
        "custom_id": tiktok_username,
        "application_context": {
            "brand_name": "Quid Game TikTok",
            "user_action": "SUBSCRIBE_NOW",
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
    }
    if email:
        body["subscriber"] = {"email_address": email}

    resp = requests.post(
        f"{_base_url(mode)}/v1/billing/subscriptions",
        headers=_headers(client_id, client_secret, mode, {"Prefer": "return=representation"}),
        json=body,
        timeout=10,
    )
    if resp.status_code not in (200, 201):
        raise PayPalError(resp.text)
    return resp.json()


def approval_url(suscripcion: dict) -> str | None:
    """Extrae el link 'approve' (a donde hay que redirigir al comprador)
    de la respuesta de crear_suscripcion()."""
    for link in suscripcion.get("links", []):
        if link.get("rel") == "approve":
            return link.get("href")
    return None


def get_subscription(client_id: str, client_secret: str, mode: str, subscription_id: str) -> dict:
    resp = requests.get(
        f"{_base_url(mode)}/v1/billing/subscriptions/{subscription_id}",
        headers=_headers(client_id, client_secret, mode),
        timeout=10,
    )
    if resp.status_code != 200:
        raise PayPalError(resp.text)
    return resp.json()


def cancel_subscription(client_id: str, client_secret: str, mode: str, subscription_id: str, reason: str = "Cancelada por el administrador") -> None:
    resp = requests.post(
        f"{_base_url(mode)}/v1/billing/subscriptions/{subscription_id}/cancel",
        headers=_headers(client_id, client_secret, mode),
        json={"reason": reason},
        timeout=10,
    )
    if resp.status_code not in (204,):
        raise PayPalError(resp.text)


def verify_webhook_signature(
    client_id: str,
    client_secret: str,
    mode: str,
    webhook_id: str,
    headers: dict,
    raw_body: bytes,
) -> bool:
    """Verifica un webhook de PayPal contra su API de verificación
    (a diferencia de Lemon Squeezy, PayPal no usa un HMAC que puedas
    calcular localmente sin llamar a su API: hay que mandarle de vuelta
    las cabeceras de la firma + el body y te dice VERIFIED / FAILURE).
    """
    if not webhook_id:
        return False
    try:
        import json
        body = {
            "auth_algo": headers.get("Paypal-Auth-Algo"),
            "cert_url": headers.get("Paypal-Cert-Url"),
            "transmission_id": headers.get("Paypal-Transmission-Id"),
            "transmission_sig": headers.get("Paypal-Transmission-Sig"),
            "transmission_time": headers.get("Paypal-Transmission-Time"),
            "webhook_id": webhook_id,
            "webhook_event": json.loads(raw_body.decode("utf-8")),
        }
        resp = requests.post(
            f"{_base_url(mode)}/v1/notifications/verify-webhook-signature",
            headers=_headers(client_id, client_secret, mode),
            json=body,
            timeout=10,
        )
        if resp.status_code != 200:
            return False
        return resp.json().get("verification_status") == "SUCCESS"
    except Exception:
        return False
