import json

from flask import Blueprint, request, current_app, abort

from extensions import db
from models import Subscription, WebhookEvent
import paypal_client
import licensing
import emailer

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")

# Pasarela activa: PayPal (Subscriptions).
#
# NOTA: esta es la vía "async" de siempre. Desde que existe el respaldo
# síncrono en /gracias (routes/public.py), este webhook ya no es el ÚNICO
# lugar donde se emite la licencia la primera vez -- pero SIGUE siendo el
# único lugar que procesa renovaciones, cancelaciones y suspensiones, así
# que la URL debe seguir bien configurada en developer.paypal.com.


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
                    sub = licensing.upsert_subscription_paypal(datos, event_name, config)
                except paypal_client.PayPalError as e:
                    print(f"[webhooks] No se pudo recuperar suscripción {sub_id}: {e}")
                    sub = None
            resource_para_licencia = {"custom_id": sub.licenses.first().tiktok_username if (sub and sub.licenses.first()) else ""}
        else:
            sub = licensing.upsert_subscription_paypal(resource, event_name, config)
            resource_para_licencia = resource

        if sub is not None:
            db.session.flush()

        if event_name in ("BILLING.SUBSCRIPTION.ACTIVATED", "PAYMENT.SALE.COMPLETED") and sub is not None:
            try:
                tipo, kwargs = licensing.emitir_o_renovar_licencia_paypal(sub, resource_para_licencia, event_name, config)
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
