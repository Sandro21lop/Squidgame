import os

from flask import Blueprint, render_template, redirect, current_app, request, \
    send_file, abort, flash, url_for

from extensions import db
from models import License
from license_generator import PLANES, normalizar_tiktok
import paypal_client
from content_pruebas import PRUEBAS

public_bp = Blueprint("public", __name__)

_CHECKOUT_URLS = {
    "mensual": "PAYPAL_CHECKOUT_URL_MENSUAL",
    "semestral": "PAYPAL_CHECKOUT_URL_SEMESTRAL",
    "anual": "PAYPAL_CHECKOUT_URL_ANUAL",
}

_PLAN_ID_KEYS = {
    "mensual": "PAYPAL_PLAN_ID_MENSUAL",
    "semestral": "PAYPAL_PLAN_ID_SEMESTRAL",
    "anual": "PAYPAL_PLAN_ID_ANUAL",
}


def _checkout_urls(app):
    return {plan: app.config[key] for plan, key in _CHECKOUT_URLS.items()}


def _pasarela_configurada(app):
    """True cuando ya pusiste client id/secret de PayPal y el Plan ID de
    los planes que REALMENTE existen en PLANES (hoy solo "mensual").
    Mientras falte algo, /comprar cae al modo manual (link fijo o '#')
    para no romper la landing."""
    return bool(
        app.config["PAYPAL_CLIENT_ID"]
        and app.config["PAYPAL_CLIENT_SECRET"]
        and all(app.config[_PLAN_ID_KEYS[plan]] for plan in PLANES)
    )


@public_bp.route("/")
def landing():
    return render_template(
        "landing.html",
        game_name=current_app.config["GAME_NAME"],
        planes=PLANES,
        checkout_urls=_checkout_urls(current_app),
        pruebas=PRUEBAS,
    )


@public_bp.route("/comprar", methods=["GET", "POST"])
@public_bp.route("/comprar/<plan>", methods=["GET", "POST"])
def comprar(plan="mensual"):
    """Botón de compra.

    - Si la pasarela NO está configurada todavía (falta API key / store id /
      variant ids en el .env), cae al link fijo de siempre (pago manual,
      WhatsApp, etc.) para no romper la landing mientras la conectas.
    - Si SÍ está configurada, pide el usuario de TikTok aquí mismo y crea
      una suscripción de PayPal por API con ese usuario metido en
      custom_id. Así, cuando el webhook confirme el pago, ya sabe para
      quién generar la licencia — sin que tengas que hacer nada a mano.
    """
    if plan not in PLANES:
        plan = "mensual"

    if not _pasarela_configurada(current_app):
        return redirect(_checkout_urls(current_app)[plan])

    error = None
    tiktok_username = ""
    email = ""
    if request.method == "POST":
        tiktok_username = normalizar_tiktok(request.form.get("tiktok_username", ""))
        email = (request.form.get("email", "") or "").strip().lower()

        if not tiktok_username:
            error = "Escribe tu usuario de TikTok (el mismo con el que transmites)."
        elif not email or "@" not in email or "." not in email.split("@")[-1]:
            error = "Escribe un correo electrónico válido: ahí te llega la clave de licencia."
        else:
            return_url = url_for("public.gracias", u=tiktok_username, _external=True)
            cancel_url = url_for("public.comprar", plan=plan, _external=True)
            try:
                suscripcion = paypal_client.crear_suscripcion(
                    client_id=current_app.config["PAYPAL_CLIENT_ID"],
                    client_secret=current_app.config["PAYPAL_CLIENT_SECRET"],
                    mode=current_app.config["PAYPAL_MODE"],
                    plan_id=current_app.config[_PLAN_ID_KEYS[plan]],
                    tiktok_username=tiktok_username,
                    return_url=return_url,
                    cancel_url=cancel_url,
                    email=email,
                )
                checkout_url = paypal_client.approval_url(suscripcion)
                if not checkout_url:
                    raise paypal_client.PayPalError("Sin link de aprobación en la respuesta")
                return redirect(checkout_url)
            except paypal_client.PayPalError as e:
                print(f"[comprar] Error PayPal: {e}")
                error = "No pudimos iniciar el pago. Intenta de nuevo en un momento."

    return render_template(
        "comprar.html",
        game_name=current_app.config["GAME_NAME"],
        plan=plan,
        info=PLANES[plan],
        error=error,
        tiktok_username=tiktok_username,
        email=email,
    )


@public_bp.route("/gracias")
def gracias():
    """Página a la que PayPal redirige justo después del pago.

    El webhook (que llega por separado, casi siempre en 1-2 segundos) es
    quien realmente genera la licencia. Esta página busca por usuario de
    TikTok (?u=...) y, si ya está lista, la muestra; si no, se refresca
    sola un par de veces por si el webhook todavía no llegó."""
    tiktok_username = normalizar_tiktok(request.args.get("u", ""))
    licencia = None
    if tiktok_username:
        licencia = (
            License.query
            .filter_by(tiktok_username=tiktok_username, origen="paypal")
            .order_by(License.created_at.desc())
            .first()
        )
    return render_template(
        "gracias.html",
        game_name=current_app.config["GAME_NAME"],
        licencia=licencia,
        tiktok_username=tiktok_username,
    )


@public_bp.route("/mi-cuenta", methods=["GET", "POST"])
def mi_cuenta():
    """El cliente pone su usuario de TikTok y le mostramos el estado de su
    suscripción de PayPal (consultado en vivo por API) con un botón para
    cancelarla él mismo. A diferencia de Lemon Squeezy, PayPal no ofrece
    una URL de "customer portal" firmada por API, así que armamos la
    vista nosotros mismos; para cambiar de tarjeta/método de pago el
    cliente debe hacerlo desde su cuenta de paypal.com."""
    error = None
    suscripcion = None
    tiktok_username = ""
    if request.method == "POST":
        tiktok_username = normalizar_tiktok(request.form.get("tiktok_username", ""))
        if not tiktok_username:
            error = "Escribe tu usuario de TikTok."
        else:
            lic = (
                License.query
                .filter_by(tiktok_username=tiktok_username, origen="paypal")
                .order_by(License.created_at.desc())
                .first()
            )
            if not lic or not lic.subscription:
                error = (
                    "No encontramos una suscripción de PayPal para ese usuario. "
                    "Si tu licencia se activó manualmente (pago directo), escríbenos "
                    "para renovar o cancelar."
                )
            else:
                try:
                    datos = paypal_client.get_subscription(
                        current_app.config["PAYPAL_CLIENT_ID"],
                        current_app.config["PAYPAL_CLIENT_SECRET"],
                        current_app.config["PAYPAL_MODE"],
                        lic.subscription.paypal_subscription_id,
                    )
                    suscripcion = {
                        "id": lic.subscription.id,
                        "status": datos.get("status"),
                        "plan": lic.subscription.plan,
                        "next_billing": (datos.get("billing_info") or {}).get("next_billing_time"),
                    }
                except paypal_client.PayPalError:
                    error = "No pudimos consultar tu suscripción. Intenta de nuevo en un momento."

    return render_template(
        "mi_cuenta.html",
        game_name=current_app.config["GAME_NAME"],
        error=error,
        suscripcion=suscripcion,
        tiktok_username=tiktok_username,
    )


@public_bp.route("/mi-cuenta/cancelar/<int:subscription_id>", methods=["POST"])
def mi_cuenta_cancelar(subscription_id):
    """Cancelación self-service: el cliente debe volver a escribir su
    usuario de TikTok como confirmación (evita que alguien cancele la
    suscripción de otro solo por adivinar el subscription_id)."""
    from models import Subscription

    tiktok_username = normalizar_tiktok(request.form.get("tiktok_username", ""))
    sub = Subscription.query.get_or_404(subscription_id)
    lic = sub.licenses.first()

    if not tiktok_username or not lic or lic.tiktok_username != tiktok_username:
        flash("No pudimos confirmar tu usuario de TikTok. Intenta de nuevo.", "danger")
        return redirect(url_for("public.mi_cuenta"))

    try:
        paypal_client.cancel_subscription(
            current_app.config["PAYPAL_CLIENT_ID"],
            current_app.config["PAYPAL_CLIENT_SECRET"],
            current_app.config["PAYPAL_MODE"],
            sub.paypal_subscription_id,
            reason="Cancelada por el cliente desde /mi-cuenta",
        )
        sub.status = "cancelled"
        db.session.commit()
        flash("Tu suscripción fue cancelada. Seguirá activa hasta el fin del ciclo ya pagado.", "success")
    except paypal_client.PayPalError:
        flash("No pudimos cancelar tu suscripción. Intenta de nuevo o escríbenos.", "danger")

    return redirect(url_for("public.mi_cuenta"))


@public_bp.route("/descargar", methods=["GET", "POST"])
def descargar():
    """El cliente ingresa su clave de licencia para bajar el instalador.
    Solo se permite si la licencia está vigente (o en período de gracia)
    y no fue bloqueada manualmente."""
    error = None
    if request.method == "POST":
        license_key = (request.form.get("license_key") or "").strip().upper()

        if not license_key:
            error = "Ingresa tu clave de licencia."
        else:
            lic = License.query.filter_by(license_key=license_key).first()

            if not lic:
                error = "Clave de licencia no encontrada. Verifica que la copiaste completa."
            elif lic.esta_bloqueada():
                error = "Esta licencia fue suspendida. Contáctanos si crees que es un error."
            elif not lic.esta_vigente(current_app.config["DIAS_GRACIA"]):
                error = (
                    "Tu licencia está vencida. Si tienes el pago automático activado, se "
                    "reactivará sola con el próximo cobro; si no, vuelve a suscribirte y "
                    "se restablecerá esta misma clave."
                )
            else:
                url_externa = current_app.config["DOWNLOAD_LATEST_URL"]
                if url_externa:
                    return redirect(url_externa)

                path = current_app.config["DOWNLOAD_LATEST_PATH"]
                if not os.path.exists(path):
                    error = "El instalador no está disponible en este momento, contáctanos."
                else:
                    return send_file(path, as_attachment=True)

    return render_template("descargar.html", error=error, game_name=current_app.config["GAME_NAME"])