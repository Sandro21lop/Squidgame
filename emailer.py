"""
emailer.py — Envío de correos transaccionales (licencias, renovaciones)
por SMTP directo. Pensado para Render de pago, donde el puerto 587/465
sí sale (a diferencia del plan free, que bloquea SMTP saliente).

Configura en tu .env:
    SMTP_HOST=smtp.tu-proveedor.com
    SMTP_PORT=587
    SMTP_USER=tu-usuario
    SMTP_PASSWORD=tu-password-o-app-password
    SMTP_SECURITY=starttls        # o "ssl" si usas el puerto 465
    EMAIL_FROM=Quid Game TikTok <licencias@tudominio.com>

Sirve con Gmail (con "contraseña de aplicación"), Zoho Mail, un dominio
propio con SMTP de tu hosting, etc. Si SMTP_HOST está vacío, las
funciones no fallan: solo registran en consola que no se pudo enviar
(así nunca tumbas el webhook de pagos por un problema de correo).
"""
import smtplib
import ssl
from email.message import EmailMessage


def _smtp_configurado(config) -> bool:
    return bool(config.get("SMTP_HOST") and config.get("EMAIL_FROM"))


def enviar_email(config, destinatario: str, asunto: str, html: str, texto_plano: str = "") -> bool:
    """Envía un correo HTML. Devuelve True/False, nunca lanza excepción
    hacia arriba — un fallo de correo no debe tumbar un webhook de pago
    ni la generación de una licencia."""
    if not destinatario:
        print("[emailer] Sin destinatario, no se envía nada.")
        return False
    if not _smtp_configurado(config):
        print(f"[emailer] SMTP no configurado — no se pudo enviar '{asunto}' a {destinatario}.")
        return False

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = config["EMAIL_FROM"]
    msg["To"] = destinatario
    msg.set_content(texto_plano or "Tu cliente de correo no soporta HTML.")
    msg.add_alternative(html, subtype="html")

    try:
        host = config["SMTP_HOST"]
        port = config["SMTP_PORT"]
        user = config.get("SMTP_USER") or ""
        password = config.get("SMTP_PASSWORD") or ""
        seguridad = (config.get("SMTP_SECURITY") or "starttls").lower()

        if seguridad == "ssl":
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=15) as server:
                if user:
                    server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.starttls(context=ssl.create_default_context())
                if user:
                    server.login(user, password)
                server.send_message(msg)
        print(f"[emailer] Enviado '{asunto}' a {destinatario}.")
        return True
    except Exception as e:
        print(f"[emailer] ERROR enviando a {destinatario}: {e}")
        return False


def _plantilla_base(config, titulo: str, cuerpo_html: str) -> str:
    game_name = config.get("GAME_NAME", "Quid Game TikTok")
    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif; background:#0f0f14; padding:32px 16px;">
      <div style="max-width:520px; margin:0 auto; background:#17171f; border-radius:14px;
                  padding:32px; color:#eaeaea;">
        <h1 style="font-size:20px; margin:0 0 18px; color:#ff2d55;">{game_name}</h1>
        <h2 style="font-size:17px; margin:0 0 14px;">{titulo}</h2>
        {cuerpo_html}
        <p style="margin-top:28px; font-size:12px; color:#8a8a95;">
          Si no reconoces esta compra, ignora este correo o contáctanos.
        </p>
      </div>
    </div>
    """


def enviar_licencia_nueva(config, destinatario: str, tiktok_username: str, license_key: str,
                           plan_nombre: str, expira) -> bool:
    base_url = config.get("PUBLIC_BASE_URL", "")
    cuerpo = f"""
      <p>¡Gracias por tu compra! Tu licencia ya está activa para <b>@{tiktok_username}</b>.</p>
      <p style="margin:18px 0; padding:14px 16px; background:#0f0f14; border-radius:10px;
                font-family:monospace; font-size:15px; word-break:break-all; border:1px solid #2a2a35;">
        {license_key}
      </p>
      <p><b>Plan:</b> {plan_nombre}<br><b>Vigente hasta:</b> {expira.strftime('%Y-%m-%d')}</p>
      <p>Pega esta clave dentro del juego cuando te la pida al abrirlo (una sola vez).
         No compartas esta clave: queda ligada a tu cuenta y a un solo equipo.</p>
      <p><a href="{base_url}/descargar" style="color:#ff2d55;">Descargar el instalador</a></p>
    """
    html = _plantilla_base(config, "Tu licencia está lista", cuerpo)
    texto = (
        f"Tu clave de licencia: {license_key}\n"
        f"Plan: {plan_nombre}\nVigente hasta: {expira.strftime('%Y-%m-%d')}\n"
        f"Descarga: {base_url}/descargar"
    )
    return enviar_email(config, destinatario, f"Tu licencia de {config.get('GAME_NAME')}", html, texto)


def enviar_licencia_renovada(config, destinatario: str, tiktok_username: str,
                              plan_nombre: str, renueva_el) -> bool:
    fecha = renueva_el.strftime('%Y-%m-%d') if renueva_el else "—"
    cuerpo = f"""
      <p>Tu suscripción de <b>@{tiktok_username}</b> se renovó correctamente. No necesitas
         hacer nada: tu misma clave de licencia sigue funcionando.</p>
      <p><b>Plan:</b> {plan_nombre}<br><b>Próxima renovación:</b> {fecha}</p>
    """
    html = _plantilla_base(config, "Tu licencia se renovó", cuerpo)
    return enviar_email(config, destinatario, f"Renovación confirmada — {config.get('GAME_NAME')}", html)


def enviar_licencia_reactivada(config, destinatario: str, tiktok_username: str, license_key: str,
                                plan_nombre: str, renueva_el) -> bool:
    fecha = renueva_el.strftime('%Y-%m-%d') if renueva_el else "—"
    base_url = config.get("PUBLIC_BASE_URL", "")
    cuerpo = f"""
      <p>¡Tu pago se procesó correctamente! Reactivamos la suscripción de <b>@{tiktok_username}</b>
         y te devolvemos <b>la misma clave de licencia</b> que ya tenías — no necesitas
         activar el juego de nuevo si lo tenías instalado en el mismo equipo.</p>
      <p style="margin:18px 0; padding:14px 16px; background:#0f0f14; border-radius:10px;
                font-family:monospace; font-size:15px; word-break:break-all; border:1px solid #2a2a35;">
        {license_key}
      </p>
      <p><b>Plan:</b> {plan_nombre}<br><b>Próxima renovación:</b> {fecha}</p>
      <p><a href="{base_url}/descargar" style="color:#ff2d55;">Descargar el instalador</a></p>
    """
    html = _plantilla_base(config, "Tu licencia fue reactivada", cuerpo)
    texto = (
        f"Tu clave de licencia (la misma de antes): {license_key}\n"
        f"Plan: {plan_nombre}\nPróxima renovación: {fecha}\n"
        f"Descarga: {base_url}/descargar"
    )
    return enviar_email(config, destinatario, f"Tu licencia fue reactivada — {config.get('GAME_NAME')}", html, texto)


def enviar_licencia_cancelada(config, destinatario: str, tiktok_username: str, sigue_hasta) -> bool:
    fecha = sigue_hasta.strftime('%Y-%m-%d') if sigue_hasta else "el final de tu período pagado"
    cuerpo = f"""
      <p>Se canceló la suscripción de <b>@{tiktok_username}</b>. Puedes seguir usando el
         juego hasta <b>{fecha}</b>; después de esa fecha la licencia dejará de validar.</p>
      <p>Si fue un error o quieres reactivarla, entra a la página del juego y suscríbete de nuevo.</p>
    """
    html = _plantilla_base(config, "Tu suscripción fue cancelada", cuerpo)
    return enviar_email(config, destinatario, f"Suscripción cancelada — {config.get('GAME_NAME')}", html)
