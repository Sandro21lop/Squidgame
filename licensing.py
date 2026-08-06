"""
licensing.py — Lógica compartida para emitir/renovar licencias a partir de
datos de una suscripción de PayPal.

Antes esto vivía solo dentro de routes/webhooks.py y SOLO se ejecutaba
cuando el webhook de PayPal llegaba. El problema: si el webhook no llega
(URL mal configurada en el dashboard de PayPal, PayPal reintentando,
caída momentánea, etc.) el cliente pagó pero se queda sin licencia y sin
poder descargar, viendo la pantalla de "Confirmando tu pago..." para
siempre.

Ahora esta lógica vive aquí para que routes/webhooks.py (el camino async,
de siempre) y routes/public.py -> /gracias (un camino síncrono de
respaldo, que se dispara cuando el comprador vuelve del checkout de
PayPal) puedan usar exactamente el mismo código. Así, aunque el webhook
falle o tarde, en cuanto el comprador vuelve a /gracias con su
subscription_id ya activo, se le emite la licencia en el momento.
"""
from datetime import datetime

from extensions import db
from models import Customer, Subscription, License
from license_generator import generar_licencia, normalizar_tiktok, PLANES

PAYPAL_STATUS_MAP = {
    "ACTIVE": "active",
    "APPROVAL_PENDING": "unpaid",
    "APPROVED": "unpaid",
    "SUSPENDED": "paused",
    "CANCELLED": "cancelled",
    "EXPIRED": "expired",
}


def parse_fecha(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def plan_desde_paypal_plan_id(plan_id, config):
    plan_id = str(plan_id or "")
    mapeo = {}
    for plan, cfg_key in (
        ("mensual", "PAYPAL_PLAN_ID_MENSUAL"),
        ("semestral", "PAYPAL_PLAN_ID_SEMESTRAL"),
        ("anual", "PAYPAL_PLAN_ID_ANUAL"),
    ):
        valor = str(config.get(cfg_key) or "")
        if valor:
            mapeo[valor] = plan
    return mapeo.get(plan_id, "mensual")


def upsert_customer_paypal(email, name, payer_id):
    if not email:
        return None
    customer = Customer.query.filter_by(email=email).first()
    if not customer:
        customer = Customer(email=email, paypal_payer_id=str(payer_id or ""))
        db.session.add(customer)
        db.session.flush()
    customer.name = name or customer.name
    if payer_id:
        customer.paypal_payer_id = str(payer_id)
    return customer


def upsert_subscription_paypal(resource, event_name, config):
    """resource: el dict de una suscripción de PayPal (ya sea de un
    webhook o de una llamada directa a GET /v1/billing/subscriptions/{id})."""
    paypal_sub_id = str(resource.get("id"))
    sub = Subscription.query.filter_by(paypal_subscription_id=paypal_sub_id).first()

    subscriber = resource.get("subscriber", {}) or {}
    email = subscriber.get("email_address")
    name_obj = subscriber.get("name", {}) or {}
    name = " ".join(filter(None, [name_obj.get("given_name"), name_obj.get("surname")])) or None
    payer_id = subscriber.get("payer_id")

    customer = upsert_customer_paypal(email, name, payer_id)
    if not customer:
        return None

    if not sub:
        sub = Subscription(paypal_subscription_id=paypal_sub_id, customer_id=customer.id)
        db.session.add(sub)

    sub.customer_id = customer.id
    plan_id = resource.get("plan_id")
    sub.paypal_plan_id = str(plan_id or "")
    sub.plan = plan_desde_paypal_plan_id(plan_id, config)

    status = resource.get("status") or ("ACTIVE" if event_name == "PAYMENT.SALE.COMPLETED" else None)
    if status:
        sub.status = PAYPAL_STATUS_MAP.get(status, sub.status or "active")

    billing_info = resource.get("billing_info", {}) or {}
    next_billing = billing_info.get("next_billing_time")
    if next_billing:
        sub.renews_at = parse_fecha(next_billing)

    return sub


def marcar_intento_completado(tiktok_username, sub):
    """Cuando un pago se confirma (webhook o /gracias), busca el intento de
    compra pendiente más reciente de este usuario de TikTok y lo marca como
    completado — así en el panel admin se ve el embudo: quién entró al
    botón de pago vs. quién terminó pagando."""
    from models import IntentoCompra

    if not tiktok_username:
        return
    intento = (
        IntentoCompra.query
        .filter_by(tiktok_username=tiktok_username, completado=False)
        .order_by(IntentoCompra.created_at.desc())
        .first()
    )
    if intento:
        intento.completado = True
        intento.completado_at = datetime.utcnow()
        intento.subscription_id = sub.id


def emitir_o_renovar_licencia_paypal(sub, resource, event_name, config):
    if sub is None:
        return None, None

    tiktok_username = normalizar_tiktok(resource.get("custom_id", "") or "")
    licencia_existente = sub.licenses.first()

    if licencia_existente is None:
        if not tiktok_username:
            return None, None

        # ¿Este usuario de TikTok ya tuvo una licencia antes (de una
        # suscripción anterior, cancelada o vencida)? Si volvió a pagar,
        # le devolvemos la MISMA clave en vez de generar una nueva: así no
        # pierde el equipo ya vinculado (instance_id) ni tiene que volver
        # a "activarla" en el juego con una clave distinta.
        lic_anterior = (
            License.query
            .filter_by(tiktok_username=tiktok_username, origen="paypal")
            .filter(License.subscription_id != sub.id)
            .order_by(License.created_at.desc())
            .first()
        )

        if lic_anterior is not None and not lic_anterior.bloqueada_manualmente:
            lic_anterior.subscription_id = sub.id
            lic_anterior.plan = sub.plan
            lic_anterior.email = (sub.customer.email if sub.customer else lic_anterior.email)
            plan_nombre = PLANES.get(sub.plan, {}).get("nombre", sub.plan)
            marcar_intento_completado(tiktok_username, sub)
            return "reactivada", dict(
                destinatario=(sub.customer.email if sub.customer else lic_anterior.email),
                tiktok_username=tiktok_username, license_key=lic_anterior.license_key,
                plan_nombre=plan_nombre, renueva_el=sub.renews_at,
            )

        clave, expira = generar_licencia(tiktok_username, sub.plan, config["SECRET_KEY"])
        lic = License(
            license_key=clave,
            origen="paypal",
            tiktok_username=tiktok_username,
            plan=sub.plan,
            expira_at=expira,
            email=(sub.customer.email if sub.customer else None),
            subscription_id=sub.id,
            activation_limit=1,
        )
        db.session.add(lic)
        plan_nombre = PLANES.get(sub.plan, {}).get("nombre", sub.plan)
        marcar_intento_completado(tiktok_username, sub)
        return "nueva", dict(
            destinatario=(sub.customer.email if sub.customer else None),
            tiktok_username=tiktok_username, license_key=clave,
            plan_nombre=plan_nombre, expira=expira,
        )

    if event_name == "PAYMENT.SALE.COMPLETED":
        plan_nombre = PLANES.get(sub.plan, {}).get("nombre", sub.plan)
        marcar_intento_completado(licencia_existente.tiktok_username, sub)
        return "renovada", dict(
            destinatario=(sub.customer.email if sub.customer else None),
            tiktok_username=licencia_existente.tiktok_username,
            plan_nombre=plan_nombre, renueva_el=sub.renews_at,
        )

    return None, None
