import os

from flask import Blueprint, render_template, redirect, current_app, request, \
    send_file, abort, flash, url_for

from extensions import db
from models import License
from license_generator import PLANES, normalizar_tiktok
from lemonsqueezy_client import crear_checkout, get_subscription, LemonSqueezyError
from content_pruebas import PRUEBAS

public_bp = Blueprint("public", __name__)

_CHECKOUT_URLS = {
    "mensual": "LS_CHECKOUT_URL_MENSUAL",
    "semestral": "LS_CHECKOUT_URL_SEMESTRAL",
    "anual": "LS_CHECKOUT_URL_ANUAL",
}

_VARIANT_KEYS = {
    "mensual": "LS_VARIANT_ID_MENSUAL",
    "semestral": "LS_VARIANT_ID_SEMESTRAL",
    "anual": "LS_VARIANT_ID_ANUAL",
}


def _checkout_urls(app):
    return {plan: app.config[key] for plan, key in _CHECKOUT_URLS.items()}


def _pasarela_configurada(app):
    """True solo cuando ya pusiste API key, store id y los 3 variant id en
    el .env. Mientras falte algo, /comprar cae al modo manual (link fijo
    o '#') para no romper la landing."""
    return bool(
        app.config["LS_API_KEY"]
        and app.config["LS_STORE_ID"]
        and all(app.config[key] for key in _VARIANT_KEYS.values())
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
      un checkout de Lemon Squeezy por API con ese usuario metido como
      custom data. Así, cuando el webhook confirme el pago, ya sabe para
      quién generar la licencia — sin que tengas que hacer nada a mano.
    """
    if plan not in PLANES:
        plan = "mensual"

    if not _pasarela_configurada(current_app):
        return redirect(_checkout_urls(current_app)[plan])

    error = None
    if request.method == "POST":
        tiktok_username = normalizar_tiktok(request.form.get("tiktok_username", ""))
        if not tiktok_username:
            error = "Escribe tu usuario de TikTok (el mismo con el que transmites)."
        else:
            redirect_url = url_for("public.gracias", u=tiktok_username, _external=True)
            try:
                checkout_url = crear_checkout(
                    api_key=current_app.config["LS_API_KEY"],
                    store_id=current_app.config["LS_STORE_ID"],
                    variant_id=current_app.config[_VARIANT_KEYS[plan]],
                    tiktok_username=tiktok_username,
                    redirect_url=redirect_url,
                )
                return redirect(checkout_url)
            except LemonSqueezyError:
                error = "No pudimos iniciar el pago. Intenta de nuevo en un momento."

    return render_template(
        "comprar.html",
        game_name=current_app.config["GAME_NAME"],
        plan=plan,
        info=PLANES[plan],
        error=error,
    )


@public_bp.route("/gracias")
def gracias():
    """Página a la que Lemon Squeezy redirige justo después del pago.

    El webhook (que llega por separado, casi siempre en 1-2 segundos) es
    quien realmente genera la licencia. Esta página busca por usuario de
    TikTok (?u=...) y, si ya está lista, la muestra; si no, se refresca
    sola un par de veces por si el webhook todavía no llegó."""
    tiktok_username = normalizar_tiktok(request.args.get("u", ""))
    licencia = None
    if tiktok_username:
        licencia = (
            License.query
            .filter_by(tiktok_username=tiktok_username, origen="lemonsqueezy")
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
    """El cliente pone su usuario de TikTok y lo mandamos al Customer Portal
    de Lemon Squeezy — ahí puede ver su suscripción, cambiar tarjeta,
    descargar facturas y cancelar él mismo. No armamos login propio: la
    URL que da Lemon Squeezy ya viene firmada y logueada, válida 24h."""
    error = None
    if request.method == "POST":
        tiktok_username = normalizar_tiktok(request.form.get("tiktok_username", ""))
        if not tiktok_username:
            error = "Escribe tu usuario de TikTok."
        else:
            lic = (
                License.query
                .filter_by(tiktok_username=tiktok_username, origen="lemonsqueezy")
                .order_by(License.created_at.desc())
                .first()
            )
            if not lic or not lic.subscription:
                error = (
                    "No encontramos una suscripción de Lemon Squeezy para ese usuario. "
                    "Si tu licencia se activó manualmente (pago directo), escríbenos "
                    "para renovar o cancelar."
                )
            else:
                try:
                    datos = get_subscription(
                        current_app.config["LS_API_KEY"],
                        lic.subscription.ls_subscription_id,
                    )
                    portal_url = datos["data"]["attributes"]["urls"]["customer_portal"]
                    if not portal_url:
                        error = "Tu suscripción no tiene un portal disponible en este momento. Escríbenos."
                    else:
                        return redirect(portal_url)
                except (LemonSqueezyError, KeyError):
                    error = "No pudimos abrir tu portal de cliente. Intenta de nuevo en un momento."

    return render_template(
        "mi_cuenta.html",
        game_name=current_app.config["GAME_NAME"],
        error=error,
    )


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
                error = "Tu licencia está vencida. Renueva tu plan para seguir descargando."
            else:
                path = current_app.config["DOWNLOAD_LATEST_PATH"]
                if not os.path.exists(path):
                    error = "El instalador no está disponible en este momento, contáctanos."
                else:
                    return send_file(path, as_attachment=True)

    return render_template("descargar.html", error=error, game_name=current_app.config["GAME_NAME"])
