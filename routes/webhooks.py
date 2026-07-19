import json
from datetime import datetime

from flask import Blueprint, request, current_app, abort

from extensions import db
from models import Customer, Subscription, License, WebhookEvent
import paypal_client
from license_generator import generar_licencia, normalizar_tiktok, PLANES
import emailer

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")

# Pasarela activa: PayPal (Subscriptions).

_PAYPAL_STATUS_MAP = {
    "ACTIVE": "active",
    "APPROVAL_PENDING": "unpaid",
    "APPROVED": "unpaid",
    "SUSPENDED": "paused",
    "CANCELLED": "cancelled",
    "EXPIRED": "expired",
}


def _parse_fecha(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _plan_desde_paypal_plan_id(plan_id, config):
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


def _upsert_customer_paypal(email, name, payer_id):
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


def _upsert_subscription_paypal(resource, event_name, config):
    paypal_sub_id = str(resource.get("id"))
    sub = Subscription.query.filter_by(paypal_subscription_id=paypal_sub_id).first()

    subscriber = resource.get("subscriber", {}) or {}
    email = subscriber.get("email_address")
    name_obj = subscriber.get("name", {}) or {}
    name = " ".join(filter(None, [name_obj.get("given_name"), name_obj.get("surname")])) or None
    payer_id = subscriber.get("payer_id")

    customer = _upsert_customer_paypal(email, name, payer_id)
    if not customer:
        return None

    if not sub:
        sub = Subscription(paypal_subscription_id=paypal_sub_id, customer_id=customer.id)
        db.session.add(sub)

    sub.customer_id = customer.id
    plan_id = resource.get("plan_id")
    sub.paypal_plan_id = str(plan_id or "")
    sub.plan = _plan_desde_paypal_plan_id(plan_id, config)

    status = resource.get("status") or ("ACTIVE" if event_name == "PAYMENT.SALE.COMPLETED" else None)
    if status:
        sub.status = _PAYPAL_STATUS_MAP.get(status, sub.status or "active")

    billing_info = resource.get("billing_info", {}) or {}
    next_billing = billing_info.get("next_billing_time")
    if next_billing:
        sub.renews_at = _parse_fecha(next_billing)

    return sub


def _emitir_o_renovar_licencia_paypal(sub, resource, event_name, config):
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
        return "nueva", dict(
            destinatario=(sub.customer.email if sub.customer else None),
            tiktok_username=tiktok_username, license_key=clave,
            plan_nombre=plan_nombre, expira=expira,
        )

    if event_name == "PAYMENT.SALE.COMPLETED":
        plan_nombre = PLANES.get(sub.plan, {}).get("nombre", sub.plan)
        return "renovada", dict(
            destinatario=(sub.customer.email if sub.customer else None),
            tiktok_username=licencia_existente.tiktok_username,
            plan_nombre=plan_nombre, renueva_el=sub.renews_at,
        )

    return None, None


@webhooks_bp.route("/paypal", methods=["POST"])
def paypal_webhook():
    """Endpoint que registras en developer.paypal.com -> tu app -> Webhooks
    apuntando a https://TU-DOMINIO.com/webhooks/paypal, suscrito (al menos) a:
      - BILLING.SUBSCRIPTION.ACTIVATED
      - BILLING.SUBSCRIPTION.UPDATED
      - BILLING.SUBSCRIPTION.CANCELLED
      - BILLING.SUBSCRIPTION.SUSPENDED
      - BILLING.SUBSCRIPTION.EXPIRED
      - PAYMENT.SALE.COMPLETED   (cada cobro, incluidas renovaciones)
    """
    raw = request.get_data()
    config = current_app.config

    ok = paypal_client.verify_webhook_signature(
        client_id=config["PAYPAL_CLIENT_ID"],
        client_secret=config["PAYPAL_CLIENT_SECRET"],
        mode=config["PAYPAL_MODE"],
        webhook_id=config["PAYPAL_WEBHOOK_ID"],
        headers=request.headers,
        raw_body=raw,
    )
    if not ok:
        abort(400, "Firma inválida")

    payload = request.get_json(silent=True) or {}
    event_name = payload.get("event_type", "desconocido")
    resource = payload.get("resource", {}) or {}

    db.session.add(WebhookEvent(event_name=event_name, payload=json.dumps(payload)[:20000]))

    correo_pendiente = None

    if event_name.startswith("BILLING.SUBSCRIPTION.") or event_name == "PAYMENT.SALE.COMPLETED":
        # Para PAYMENT.SALE.COMPLETED, PayPal manda el sale en `resource`
        # pero la suscripción va en `resource['billing_agreement_id']`,
        # no en `resource['id']` — normalizamos eso aquí.
        if event_name == "PAYMENT.SALE.COMPLETED":
            sub_id = resource.get("billing_agreement_id")
            sub = Subscription.query.filter_by(paypal_subscription_id=str(sub_id)).first()
            if sub is None and sub_id:
                # Suscripción activa que aún no vimos vía BILLING.SUBSCRIPTION.*
                # (puede llegar en otro orden): la pedimos a la API para
                # tener sus datos completos y crearla.
                try:
                    datos = paypal_client.get_subscription(
                        config["PAYPAL_CLIENT_ID"], config["PAYPAL_CLIENT_SECRET"],
                        config["PAYPAL_MODE"], sub_id,
                    )
                    sub = _upsert_subscription_paypal(datos, event_name, config)
                except paypal_client.PayPalError as e:
                    print(f"[webhooks] No se pudo recuperar suscripción {sub_id}: {e}")
                    sub = None
            resource_para_licencia = {"custom_id": sub.licenses.first().tiktok_username if (sub and sub.licenses.first()) else ""}
        else:
            sub = _upsert_subscription_paypal(resource, event_name, config)
            resource_para_licencia = resource

        if sub is not None:
            db.session.flush()

        if event_name in ("BILLING.SUBSCRIPTION.ACTIVATED", "PAYMENT.SALE.COMPLETED") and sub is not None:
            try:
                tipo, kwargs = _emitir_o_renovar_licencia_paypal(sub, resource_para_licencia, event_name, config)
                correo_pendiente = (tipo, kwargs) if tipo else None
            except Exception as e:
                # Nunca dejar que un fallo generando la licencia tumbe el
                # webhook (PayPal lo reintentaría). La suscripción ya quedó
                # guardada; la licencia se puede emitir a mano si hace falta.
                print(f"[webhooks] No se pudo emitir/renovar licencia para sub {sub.id}: {e}")

        elif event_name in ("BILLING.SUBSCRIPTION.CANCELLED", "BILLING.SUBSCRIPTION.EXPIRED") and sub is not None:
            lic = sub.licenses.first()
            correo_pendiente = ("cancelada", dict(
                destinatario=(sub.customer.email if sub.customer else None),
                tiktok_username=(lic.tiktok_username if lic else ""),
                sigue_hasta=sub.ends_at,
            ))

    db.session.commit()

    if correo_pendiente:
        tipo, kwargs = correo_pendiente
        try:
            if tipo == "nueva":
                emailer.enviar_licencia_nueva(current_app.config, **kwargs)
            elif tipo == "renovada":
                emailer.enviar_licencia_renovada(current_app.config, **kwargs)
            elif tipo == "reactivada":
                emailer.enviar_licencia_reactivada(current_app.config, **kwargs)
            elif tipo == "cancelada":
                emailer.enviar_licencia_cancelada(current_app.config, **kwargs)
        except Exception as e:
            print(f"[webhooks] No se pudo enviar el correo '{tipo}': {e}")

    return {"received": True}, 200