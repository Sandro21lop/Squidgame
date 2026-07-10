import json
from datetime import datetime

from flask import Blueprint, request, current_app, abort

from extensions import db
from models import Customer, Subscription, License, WebhookEvent
from lemonsqueezy_client import verify_webhook_signature
from license_generator import generar_licencia, normalizar_tiktok, PLANES
import emailer

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")

# NOTA: cuando conectes Lemon Squeezy (o la pasarela que elijas), lo más
# limpio es que este webhook, al recibir "order_created"/"subscription_created",
# pida el usuario de TikTok en el checkout (campo personalizado) y llame a
# license_generator.generar_licencia(...) para emitir la clave — así todas
# las licencias, manuales o pagadas, quedan en el mismo formato QGT-...


def _parse_fecha(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _upsert_customer(attrs, ls_customer_id):
    email = attrs.get("user_email") or attrs.get("customer_email")
    if not email:
        return None
    customer = Customer.query.filter_by(email=email).first()
    if not customer:
        customer = Customer(email=email, ls_customer_id=str(ls_customer_id or ""))
        db.session.add(customer)
        db.session.flush()
    customer.name = attrs.get("user_name") or customer.name
    if ls_customer_id:
        customer.ls_customer_id = str(ls_customer_id)
    return customer


def _plan_desde_variant(variant_id, config):
    """Traduce el variant_id que manda Lemon Squeezy al plan interno
    (mensual/semestral/anual), usando el mismo mapeo que tienes en .env."""
    mapeo = {
        str(config.get("LS_VARIANT_ID_MENSUAL") or ""): "mensual",
        str(config.get("LS_VARIANT_ID_SEMESTRAL") or ""): "semestral",
        str(config.get("LS_VARIANT_ID_ANUAL") or ""): "anual",
    }
    return mapeo.get(str(variant_id or ""), "mensual")


def _emitir_licencia_si_falta(sub, attrs, meta, config):
    """Si esta suscripción todavía no tiene una licencia QGT-... propia,
    la genera ahora. El usuario de TikTok viaja en meta.custom_data (lo
    metimos al crear el checkout en routes/public.py). Idempotente: si
    ya existe una licencia para esta suscripción, no crea otra (esto
    puede llamarse varias veces si Lemon Squeezy reintenta el webhook,
    o si llegan tanto order_created como subscription_created).

    Devuelve True si emitió una licencia nueva (para que el caller sepa
    si debe mandar el correo de "tu licencia está lista" o no)."""
    if sub is None or sub.licenses.first() is not None:
        return False

    custom_data = (meta or {}).get("custom_data") or {}
    tiktok_username = normalizar_tiktok(custom_data.get("tiktok_username", ""))
    if not tiktok_username:
        # No debería pasar si el checkout se creó desde /comprar, pero si
        # llega una suscripción sin ese dato (ej. creada a mano en el
        # dashboard de LS), no podemos emitir la licencia: queda pendiente
        # para que la generes manualmente desde el panel admin.
        return False

    plan = _plan_desde_variant(attrs.get("variant_id"), config)
    sub.plan = plan

    clave, expira = generar_licencia(tiktok_username, plan, config["SECRET_KEY"])
    db.session.add(License(
        license_key=clave,
        origen="lemonsqueezy",
        tiktok_username=tiktok_username,
        plan=plan,
        expira_at=expira,
        email=(sub.customer.email if sub.customer else None),
        subscription_id=sub.id,
        activation_limit=1,
    ))
    return True


def _upsert_subscription(data, attrs):
    ls_sub_id = str(data.get("id"))
    sub = Subscription.query.filter_by(ls_subscription_id=ls_sub_id).first()
    customer = _upsert_customer(attrs, attrs.get("customer_id"))
    if not customer:
        return None

    if not sub:
        sub = Subscription(ls_subscription_id=ls_sub_id, customer_id=customer.id)
        db.session.add(sub)

    sub.customer_id = customer.id
    sub.variant_id = str(attrs.get("variant_id") or "")
    sub.variant_name = attrs.get("variant_name")
    sub.status = attrs.get("status") or sub.status
    sub.renews_at = _parse_fecha(attrs.get("renews_at"))
    sub.ends_at = _parse_fecha(attrs.get("ends_at"))
    sub.trial_ends_at = _parse_fecha(attrs.get("trial_ends_at"))
    sub.card_brand = attrs.get("card_brand")
    sub.card_last_four = attrs.get("card_last_four")
    return sub


@webhooks_bp.route("/lemonsqueezy", methods=["POST"])
def lemonsqueezy_webhook():
    raw = request.get_data()
    signature = request.headers.get("X-Signature", "")
    secret = current_app.config["LS_WEBHOOK_SECRET"]

    if not verify_webhook_signature(raw, signature, secret):
        abort(400, "Firma inválida")

    payload = request.get_json(silent=True) or {}
    meta = payload.get("meta", {})
    event_name = meta.get("event_name", "desconocido")
    data = payload.get("data", {})
    attrs = data.get("attributes", {})

    db.session.add(WebhookEvent(event_name=event_name, payload=json.dumps(payload)[:20000]))

    correo_pendiente = None  # (tipo, kwargs) — se envía DESPUÉS del commit

    if event_name in (
        "subscription_created",
        "subscription_updated",
        "subscription_cancelled",
        "subscription_resumed",
        "subscription_expired",
        "subscription_paused",
        "subscription_unpaused",
        "subscription_payment_success",
        "subscription_payment_failed",
        "subscription_payment_recovered",
    ):
        sub = _upsert_subscription(data, attrs)
        if sub is not None:
            db.session.flush()  # asegura sub.id antes de ligar la licencia

        if event_name in ("subscription_created", "subscription_payment_success") and sub is not None:
            licencia_ya_existia = sub.licenses.first() is not None
            emitida = _emitir_licencia_si_falta(sub, attrs, meta, current_app.config)
            destinatario = sub.customer.email if sub.customer else None
            plan_nombre = PLANES.get(sub.plan, {}).get("nombre", sub.plan)
            if emitida:
                lic_nueva = sub.licenses.first()
                correo_pendiente = ("nueva", dict(
                    destinatario=destinatario, tiktok_username=lic_nueva.tiktok_username,
                    license_key=lic_nueva.license_key, plan_nombre=plan_nombre,
                    expira=lic_nueva.expira_at,
                ))
            elif licencia_ya_existia and event_name == "subscription_payment_success":
                # No es la primera vez que se paga: es una renovación del ciclo.
                # No se genera clave nueva (la misma sigue vigente porque su
                # validez depende del estado de la suscripción, no de una
                # fecha fija dentro de la clave) — solo avisamos por correo.
                lic = sub.licenses.first()
                correo_pendiente = ("renovada", dict(
                    destinatario=destinatario,
                    tiktok_username=(lic.tiktok_username if lic else ""),
                    plan_nombre=plan_nombre, renueva_el=sub.renews_at,
                ))

        elif event_name in ("subscription_cancelled", "subscription_expired") and sub is not None:
            lic = sub.licenses.first()
            destinatario = sub.customer.email if sub.customer else None
            correo_pendiente = ("cancelada", dict(
                destinatario=destinatario,
                tiktok_username=(lic.tiktok_username if lic else ""),
                sigue_hasta=sub.ends_at,
            ))

    elif event_name == "license_key_created":
        ls_license_key_id = str(data.get("id"))
        lic = License.query.filter_by(ls_license_key_id=ls_license_key_id).first()
        customer = _upsert_customer(attrs, attrs.get("customer_id"))
        sub = None
        if attrs.get("order_id"):
            sub = Subscription.query.filter_by(
                customer_id=customer.id if customer else None,
            ).order_by(Subscription.id.desc()).first()

        if not lic:
            lic = License(
                ls_license_key_id=ls_license_key_id,
                license_key=attrs.get("key"),
                subscription_id=sub.id if sub else None,
            )
            db.session.add(lic)
        lic.ls_status = attrs.get("status", lic.ls_status)
        lic.activation_limit = attrs.get("activation_limit") or lic.activation_limit

    db.session.commit()

    if correo_pendiente:
        tipo, kwargs = correo_pendiente
        try:
            if tipo == "nueva":
                emailer.enviar_licencia_nueva(current_app.config, **kwargs)
            elif tipo == "renovada":
                emailer.enviar_licencia_renovada(current_app.config, **kwargs)
            elif tipo == "cancelada":
                emailer.enviar_licencia_cancelada(current_app.config, **kwargs)
        except Exception as e:
            # Un correo fallido nunca debe hacer que Lemon Squeezy reintente
            # el webhook completo (ya se guardó todo en la base de datos).
            print(f"[webhooks] No se pudo enviar el correo '{tipo}': {e}")

    return {"received": True}, 200
