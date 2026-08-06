"""
promo.py — Oferta por tiempo limitado, estilo Steam.

Idea: mientras la oferta está activa, se MUESTRA y se COBRA el precio de
oferta (PROMO_PRECIO). En cuanto pasa la fecha de fin (PROMO_FIN), todo
vuelve solo — sin tocar código ni PayPal a mano — al precio normal que
ya tenías en PLANES (license_generator.py).

Por defecto la oferta termina el último día del mes actual. Si quieres
una fecha distinta, pon PROMO_FIN=YYYY-MM-DD en tu .env.

Para desactivar la oferta sin borrar nada: PROMO_ACTIVA=false en el .env.
"""
import calendar
from datetime import date, datetime


def _fin_de_mes_por_defecto() -> date:
    hoy = date.today()
    ultimo_dia = calendar.monthrange(hoy.year, hoy.month)[1]
    return date(hoy.year, hoy.month, ultimo_dia)


def _parsear_fecha(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def info_precio(plan_key: str, planes: dict, app_config) -> dict:
    """Devuelve toda la info de precio para un plan, ya resuelta para HOY:

    - precio_normal: el de siempre (PLANES[plan]["precio"])
    - precio_oferta: el precio rebajado configurado
    - en_oferta: True si la oferta está activa y vigente hoy
    - precio_actual: el que hay que MOSTRAR y COBRAR ahora mismo
    - fin_oferta: fecha (date) en que termina la oferta

    Si la oferta ya venció, en_oferta=False y precio_actual vuelve a ser
    precio_normal automáticamente — no hay que desactivar nada a mano.
    """
    precio_normal = planes[plan_key]["precio"]

    activa = app_config.get("PROMO_ACTIVA", True)
    precio_oferta = app_config.get("PROMO_PRECIO", precio_normal)
    fin_oferta = _parsear_fecha(app_config.get("PROMO_FIN")) or _fin_de_mes_por_defecto()

    en_oferta = bool(activa) and date.today() <= fin_oferta and precio_oferta < precio_normal

    return {
        "precio_normal": precio_normal,
        "precio_oferta": precio_oferta,
        "en_oferta": en_oferta,
        "precio_actual": precio_oferta if en_oferta else precio_normal,
        "fin_oferta": fin_oferta,
    }


def info_precios(planes: dict, app_config) -> dict:
    """Igual que info_precio() pero para todos los planes a la vez
    (para pasarle un solo dict a la landing)."""
    return {plan_key: info_precio(plan_key, planes, app_config) for plan_key in planes}
