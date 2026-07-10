"""
API que llama el JUEGO (Quid Game TikTok) directamente, no un navegador.

POST /api/activate   { "license_key": "...", "instance_name": "PC-de-Sandro" }
POST /api/validate    { "license_key": "...", "instance_id": "..." }

Ambos devuelven siempre JSON con la forma:
{
  "ok": true/false,
  "mensaje": "texto para mostrarle al usuario en el juego",
  "instance_id": "..."   (solo activate)
}

Las licencias ya NO se validan contra Lemon Squeezy: se validan contra
nuestra propia tabla `licenses`, generadas con license_generator.py
(el usuario de TikTok va cifrado dentro de la clave misma).
"""
import os
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app, send_file

from extensions import db
from models import License

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/version", methods=["GET"])
def version():
    """El juego llama esto en cada arranque (sin necesitar la clave) para
    saber si hay una actualización disponible. No expone nada sensible."""
    return jsonify(
        version=current_app.config["DOWNLOAD_LATEST_VERSION"],
        notas=current_app.config.get("DOWNLOAD_NOTAS", ""),
    )


@api_bp.route("/download", methods=["POST"])
def download():
    """Descarga del instalador para el propio juego (a diferencia de
    /descargar, que es la página web con formulario). Requiere una
    licencia vigente — así el juego puede autoactualizarse usando la
    misma clave que ya tiene guardada localmente, sin pedírsela de nuevo
    al usuario."""
    data = request.get_json(silent=True) or {}
    license_key = (data.get("license_key") or "").strip().upper()

    if not license_key:
        return jsonify(ok=False, mensaje="Falta la clave de licencia."), 400

    lic = License.query.filter_by(license_key=license_key).first()
    if not lic:
        return jsonify(ok=False, mensaje="Clave de licencia no encontrada."), 404
    if lic.esta_bloqueada():
        return jsonify(ok=False, mensaje="Esta licencia fue suspendida."), 403
    if not lic.esta_vigente(current_app.config["DIAS_GRACIA"]):
        return jsonify(ok=False, mensaje="Tu licencia está vencida."), 402

    path = current_app.config["DOWNLOAD_LATEST_PATH"]
    if not os.path.exists(path):
        return jsonify(ok=False, mensaje="El instalador no está disponible en este momento."), 503

    return send_file(path, as_attachment=True)


@api_bp.route("/activate", methods=["POST"])
def activate():
    data = request.get_json(silent=True) or {}
    license_key = (data.get("license_key") or "").strip().upper()
    instance_name = (data.get("instance_name") or "pc-desconocido").strip()

    if not license_key:
        return jsonify(ok=False, mensaje="Falta la clave de licencia."), 400

    lic = License.query.filter_by(license_key=license_key).first()
    if not lic:
        return jsonify(ok=False, mensaje="Clave de licencia no encontrada."), 404

    if lic.esta_bloqueada():
        return jsonify(
            ok=False,
            mensaje="Esta licencia fue suspendida. Contáctanos si crees que es un error.",
        ), 403

    if not lic.esta_vigente(current_app.config["DIAS_GRACIA"]):
        return jsonify(
            ok=False,
            mensaje="Tu licencia está vencida. Renueva tu plan para seguir jugando.",
        ), 402

    # "una clave, un equipo": si ya está activada en otro equipo, se rechaza
    if lic.instance_id and lic.instance_id != instance_name:
        return jsonify(
            ok=False,
            mensaje="Esta licencia ya está activada en otro equipo. "
                    "Contáctanos para liberarla si cambiaste de PC.",
        ), 409

    lic.instance_id = instance_name
    lic.activation_usage = 1
    lic.last_validated_at = datetime.utcnow()
    db.session.commit()

    return jsonify(
        ok=True,
        mensaje="Licencia activada correctamente.",
        instance_id=instance_name,
    )


@api_bp.route("/validate", methods=["POST"])
def validate():
    data = request.get_json(silent=True) or {}
    license_key = (data.get("license_key") or "").strip().upper()
    instance_id = data.get("instance_id")

    if not license_key:
        return jsonify(ok=False, mensaje="Falta la clave de licencia."), 400

    lic = License.query.filter_by(license_key=license_key).first()
    if not lic:
        return jsonify(ok=False, mensaje="Clave de licencia no encontrada."), 404

    if lic.esta_bloqueada():
        return jsonify(
            ok=False,
            mensaje="Esta licencia fue suspendida. Contáctanos si crees que es un error.",
        ), 403

    if instance_id and lic.instance_id and instance_id != lic.instance_id:
        return jsonify(
            ok=False,
            mensaje="Esta licencia está activa en otro equipo.",
        ), 409

    if not lic.esta_vigente(current_app.config["DIAS_GRACIA"]):
        return jsonify(
            ok=False,
            mensaje="Tu suscripción no está activa. Renueva en la página del juego.",
        ), 402

    lic.last_validated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(ok=True, mensaje="Licencia válida.")
