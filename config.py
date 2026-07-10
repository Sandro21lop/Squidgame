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

    # Lemon Squeezy (pendiente de configurar — por ahora las licencias se
    # generan a mano desde el panel admin en /admin/licencias/generar)
    LS_API_KEY = os.environ.get("LEMONSQUEEZY_API_KEY", "")
    LS_WEBHOOK_SECRET = os.environ.get("LEMONSQUEEZY_WEBHOOK_SECRET", "")
    LS_STORE_ID = os.environ.get("LEMONSQUEEZY_STORE_ID", "")

    # Un variant_id de Lemon Squeezy y una checkout_url por cada plan
    LS_VARIANT_ID_MENSUAL = os.environ.get("LEMONSQUEEZY_VARIANT_ID_MENSUAL", "")
    LS_VARIANT_ID_SEMESTRAL = os.environ.get("LEMONSQUEEZY_VARIANT_ID_SEMESTRAL", "")
    LS_VARIANT_ID_ANUAL = os.environ.get("LEMONSQUEEZY_VARIANT_ID_ANUAL", "")

    LS_CHECKOUT_URL_MENSUAL = os.environ.get("LEMONSQUEEZY_CHECKOUT_URL_MENSUAL", "#")
    LS_CHECKOUT_URL_SEMESTRAL = os.environ.get("LEMONSQUEEZY_CHECKOUT_URL_SEMESTRAL", "#")
    LS_CHECKOUT_URL_ANUAL = os.environ.get("LEMONSQUEEZY_CHECKOUT_URL_ANUAL", "#")

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
