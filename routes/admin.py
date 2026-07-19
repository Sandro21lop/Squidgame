from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db
from models import AdminUser, Customer, Subscription, License
import paypal_client
from license_generator import PLANES, generar_licencia, decodificar_licencia, normalizar_tiktok
import emailer

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))

    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = AdminUser.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("admin.dashboard"))
        error = "Correo o contraseña incorrectos."

    return render_template("admin/login.html", error=error)


@admin_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
@login_required
def dashboard():
    q = request.args.get("q", "").strip()

    licencias_query = License.query
    if q:
        q_norm = normalizar_tiktok(q)
        licencias_query = licencias_query.filter(
            db.or_(
                License.tiktok_username.ilike(f"%{q_norm}%"),
                License.license_key.ilike(f"%{q}%"),
            )
        )
    licencias = licencias_query.order_by(License.created_at.desc()).limit(300).all()

    total_vigentes = sum(1 for l in licencias if l.esta_vigente(current_app.config["DIAS_GRACIA"]))
    total_vencidas_o_bloqueadas = len(licencias) - total_vigentes

    precios = {k: v["precio"] for k, v in PLANES.items()}
    mrr = 0
    for l in License.query.all():
        if l.esta_vigente(current_app.config["DIAS_GRACIA"]) and l.plan in precios:
            # normalizamos todo a "equivalente mensual" para el estimado de MRR
            dias = PLANES[l.plan]["dias"]
            mrr += (precios[l.plan] / dias) * 30

    return render_template(
        "admin/dashboard.html",
        licencias=licencias,
        q=q,
        total_vigentes=total_vigentes,
        total_vencidas_o_bloqueadas=total_vencidas_o_bloqueadas,
        mrr=round(mrr),
        planes=PLANES,
        dias_gracia=current_app.config["DIAS_GRACIA"],
    )


@admin_bp.route("/licencias/generar", methods=["GET", "POST"])
@login_required
def generar():
    clave_generada = None
    expira = None

    if request.method == "POST":
        tiktok_username = request.form.get("tiktok_username", "").strip()
        plan = request.form.get("plan", "mensual")
        nota = request.form.get("nota_admin", "").strip()
        email = request.form.get("email", "").strip()

        if not tiktok_username:
            flash("Escribe el usuario de TikTok del comprador.", "danger")
        elif plan not in PLANES:
            flash("Plan inválido.", "danger")
        else:
            clave_generada, expira = generar_licencia(
                tiktok_username, plan, current_app.config["SECRET_KEY"]
            )
            lic = License(
                license_key=clave_generada,
                origen="manual",
                tiktok_username=normalizar_tiktok(tiktok_username),
                plan=plan,
                expira_at=expira,
                email=email or None,
                activation_limit=1,
                activation_usage=0,
                nota_admin=nota or None,
            )
            db.session.add(lic)
            db.session.commit()
            flash(f"Licencia generada para @{lic.tiktok_username}.", "success")

            if email:
                enviado = emailer.enviar_licencia_nueva(
                    current_app.config, email, lic.tiktok_username,
                    clave_generada, PLANES[plan]["nombre"], expira,
                )
                if enviado:
                    flash(f"Correo enviado a {email}.", "success")
                else:
                    flash(f"No se pudo enviar el correo a {email} (revisa la config SMTP). Copia la clave manualmente.", "danger")

    return render_template(
        "admin/generar_licencia.html",
        planes=PLANES,
        clave_generada=clave_generada,
        expira=expira,
    )


@admin_bp.route("/licencias/decodificar", methods=["GET", "POST"])
@login_required
def decodificar():
    resultado = None
    clave = ""
    if request.method == "POST":
        clave = request.form.get("license_key", "").strip()
        resultado = decodificar_licencia(clave, current_app.config["SECRET_KEY"])
    return render_template("admin/decodificar_licencia.html", resultado=resultado, clave=clave)


@admin_bp.route("/licencia/<int:license_id>/bloquear", methods=["POST"])
@login_required
def bloquear_licencia(license_id):
    lic = License.query.get_or_404(license_id)
    lic.bloqueada_manualmente = not lic.bloqueada_manualmente
    lic.nota_admin = request.form.get("nota_admin", lic.nota_admin)
    db.session.commit()
    estado = "bloqueada" if lic.bloqueada_manualmente else "desbloqueada"
    flash(f"Licencia de @{lic.tiktok_username or '—'} {estado}.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/licencia/<int:license_id>/resetear-equipo", methods=["POST"])
@login_required
def resetear_equipo(license_id):
    """Libera la licencia para que pueda activarse en un equipo distinto
    (por ejemplo, si el cliente formateó su PC o cambió de computadora)."""
    lic = License.query.get_or_404(license_id)
    lic.instance_id = None
    lic.activation_usage = 0
    db.session.commit()
    flash(f"Se liberó el equipo activado para @{lic.tiktok_username or '—'}.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/licencia/<int:license_id>/renovar", methods=["POST"])
@login_required
def renovar_licencia(license_id):
    """Extiende manualmente la vigencia de una licencia manual (por ejemplo,
    si te pagan por otro medio mientras conectas la pasarela de pagos)."""
    from datetime import timedelta
    lic = License.query.get_or_404(license_id)
    plan = request.form.get("plan", lic.plan)
    if plan not in PLANES:
        flash("Plan inválido.", "danger")
        return redirect(url_for("admin.dashboard"))

    base = lic.expira_at if (lic.expira_at and lic.expira_at > datetime.utcnow()) else datetime.utcnow()
    lic.plan = plan
    lic.expira_at = base + timedelta(days=PLANES[plan]["dias"])
    db.session.commit()
    flash(f"Licencia de @{lic.tiktok_username or '—'} renovada hasta {lic.expira_at.strftime('%Y-%m-%d')}.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/suscripcion/<int:subscription_id>/cancelar", methods=["POST"])
@login_required
def cancelar_suscripcion(subscription_id):
    sub = Subscription.query.get_or_404(subscription_id)
    try:
        paypal_client.cancel_subscription(
            current_app.config["PAYPAL_CLIENT_ID"],
            current_app.config["PAYPAL_CLIENT_SECRET"],
            current_app.config["PAYPAL_MODE"],
            sub.paypal_subscription_id,
            reason="Cancelada por el administrador",
        )
        sub.status = "cancelled"
        db.session.commit()
        flash("Suscripción cancelada en PayPal.", "success")
    except paypal_client.PayPalError as e:
        flash(f"No se pudo cancelar: {e}", "danger")
    return redirect(url_for("admin.dashboard"))
