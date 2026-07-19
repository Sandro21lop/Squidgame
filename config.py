import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-cambia-esto")

    _database_url = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'quid_game_tiktok.db')}"
    )
    # Render (y Heroku) entregan la URL de Postgres como "postgres://", pero
    # SQLAlchemy 1.4+ exige "postgresql://". Sin este parche, el deploy
    # arranca pero revienta al primer query con un error críptico.
    if _database_url.startswith("postgres://"):
        _database_url = _database_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Marca / nombre del producto (cámbialo aquí y se actualiza en todo el sitio)
    GAME_NAME = os.environ.get("GAME_NAME", "Quid Game TikTok")

    # PayPal (Subscriptions). Créalas en developer.paypal.com -> tu app
    # REST -> Client ID / Secret. PAYPAL_MODE = "sandbox" mientras pruebas,
    # "live" cuando ya cobres de verdad. Si algo falta, /comprar cae al
    # modo manual (link fijo o '#') para no romper la landing.
    PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "")
    PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "")
    PAYPAL_MODE = os.environ.get("PAYPAL_MODE", "sandbox")  # "sandbox" | "live"
    # webhook ID que te da PayPal al registrar la URL /webhooks/paypal en
    # developer.paypal.com -> tu app -> Webhooks (NO es lo mismo que el
    # client secret; se usa solo para verificar la firma de cada evento).
    PAYPAL_WEBHOOK_ID = os.environ.get("PAYPAL_WEBHOOK_ID", "")

    # Un Plan ID de PayPal ("P-...", creado una vez vía API o dashboard)
    # y un checkout_url de respaldo por cada plan.
    PAYPAL_PLAN_ID_MENSUAL = os.environ.get("PAYPAL_PLAN_ID_MENSUAL", "")
    PAYPAL_PLAN_ID_SEMESTRAL = os.environ.get("PAYPAL_PLAN_ID_SEMESTRAL", "")
    PAYPAL_PLAN_ID_ANUAL = os.environ.get("PAYPAL_PLAN_ID_ANUAL", "")

    PAYPAL_CHECKOUT_URL_MENSUAL = os.environ.get("PAYPAL_CHECKOUT_URL_MENSUAL", "#")
    PAYPAL_CHECKOUT_URL_SEMESTRAL = os.environ.get("PAYPAL_CHECKOUT_URL_SEMESTRAL", "#")
    PAYPAL_CHECKOUT_URL_ANUAL = os.environ.get("PAYPAL_CHECKOUT_URL_ANUAL", "#")

    # Admin
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

    # Descargas / versión del instalador (el juego consulta esto en
    # /api/version para saber si hay una actualización disponible)
    DOWNLOAD_LATEST_PATH = os.environ.get(
        "DOWNLOAD_LATEST_PATH", "downloads/QuidGameTikTok-Setup-latest.exe"
    )
    DOWNLOAD_LATEST_VERSION = os.environ.get("DOWNLOAD_LATEST_VERSION", "1.0.0")
    DOWNLOAD_NOTAS = os.environ.get("DOWNLOAD_NOTAS", "")

    # ─────────────────────────────────────────────
    # Correo (envío de licencias por email — usa tu propio SMTP,
    # ya que Render de pago no bloquea el puerto 587/465)
    # ─────────────────────────────────────────────
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    # "ssl" (puerto 465, conexión cifrada desde el inicio) o
    # "starttls" (puerto 587, empieza en plano y sube a TLS)
    SMTP_SECURITY = os.environ.get("SMTP_SECURITY", "starttls")
    EMAIL_FROM = os.environ.get("EMAIL_FROM", "")  # ej: "Quid Game TikTok <licencias@tudominio.com>"

    # URL pública del sitio (para armar links dentro de los correos)
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://TU-DOMINIO.com")

    # Cuántos días de gracia se da tras vencer el pago antes de bloquear el juego
    DIAS_GRACIA = int(os.environ.get("DIAS_GRACIA", "3"))
