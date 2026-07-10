import secrets
from datetime import datetime

from flask_login import UserMixin

from extensions import db


def gen_id():
    return secrets.token_hex(8)


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    ls_customer_id = db.Column(db.String(64), unique=True, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    subscriptions = db.relationship(
        "Subscription", backref="customer", lazy="dynamic",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Customer {self.email}>"


class Subscription(db.Model):
    __tablename__ = "subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)

    ls_subscription_id = db.Column(db.String(64), unique=True, index=True)
    ls_order_id = db.Column(db.String(64))
    variant_id = db.Column(db.String(64))
    variant_name = db.Column(db.String(255))

    # mensual | semestral | anual
    plan = db.Column(db.String(32), default="mensual")

    # active | on_trial | past_due | paused | unpaid | cancelled | expired
    status = db.Column(db.String(32), default="active", index=True)

    renews_at = db.Column(db.DateTime, nullable=True)
    ends_at = db.Column(db.DateTime, nullable=True)
    trial_ends_at = db.Column(db.DateTime, nullable=True)

    card_brand = db.Column(db.String(32))
    card_last_four = db.Column(db.String(8))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    licenses = db.relationship(
        "License", backref="subscription", lazy="dynamic",
        cascade="all, delete-orphan"
    )

    def is_effectively_active(self, dias_gracia=3):
        """Considera activa una suscripción pagando, en trial, o recién vencida
        dentro del período de gracia (para no cortar el juego en pleno stream
        por un pago que tarda unas horas en procesarse)."""
        if self.status in ("active", "on_trial"):
            return True
        if self.status == "past_due":
            return True  # LS sigue reintentando el cobro
        if self.status in ("cancelled", "expired", "paused", "unpaid"):
            if self.ends_at:
                from datetime import timedelta
                return datetime.utcnow() <= self.ends_at + timedelta(days=dias_gracia)
            return False
        return False


class License(db.Model):
    __tablename__ = "licenses"

    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey("subscriptions.id"), nullable=True)

    ls_license_key_id = db.Column(db.String(64), unique=True, index=True)
    license_key = db.Column(db.String(128), unique=True, index=True, nullable=False)

    # espejo del estado que reporta Lemon Squeezy: active | inactive | expired | disabled
    # (solo aplica a licencias con origen="lemonsqueezy")
    ls_status = db.Column(db.String(32), default="active")

    # de dónde salió esta licencia: "manual" (generada por ti desde el panel)
    # o "lemonsqueezy" (cuando conectes la pasarela de pago)
    origen = db.Column(db.String(32), default="manual")

    # el usuario de TikTok va cifrado DENTRO de license_key, pero también lo
    # guardamos en claro aquí para poder buscarlo/mostrarlo rápido en el panel
    tiktok_username = db.Column(db.String(64), index=True)
    plan = db.Column(db.String(32), default="mensual")
    expira_at = db.Column(db.DateTime, nullable=True)

    # correo del comprador — para licencias "manual" (generadas a mano en el
    # panel) es el único lugar donde lo guardamos, ya que no hay Customer.
    # Para licencias "lemonsqueezy" el correo real vive en subscription.customer.email;
    # esta columna queda como copia de conveniencia para mostrar en el panel.
    email = db.Column(db.String(255), nullable=True)

    activation_limit = db.Column(db.Integer, default=1)
    activation_usage = db.Column(db.Integer, default=0)
    instance_id = db.Column(db.String(128), nullable=True)  # equipo donde se activó

    # control manual tuyo, independiente de Lemon Squeezy
    # (para banear a alguien sin tener que tocar nada en LS)
    bloqueada_manualmente = db.Column(db.Boolean, default=False)
    nota_admin = db.Column(db.String(500))

    last_validated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def esta_bloqueada(self):
        return self.bloqueada_manualmente

    def esta_vigente(self, dias_gracia=3):
        """¿Puede este usuario seguir jugando ahora mismo?"""
        if self.bloqueada_manualmente:
            return False
        if self.origen == "manual":
            if not self.expira_at:
                return False
            from datetime import timedelta
            return datetime.utcnow() <= self.expira_at + timedelta(days=dias_gracia)
        if self.subscription:
            return self.subscription.is_effectively_active(dias_gracia)
        return False


class WebhookEvent(db.Model):
    __tablename__ = "webhook_events"

    id = db.Column(db.Integer, primary_key=True)
    ls_event_id = db.Column(db.String(128), index=True)
    event_name = db.Column(db.String(64), index=True)
    payload = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AdminUser(UserMixin, db.Model):
    """Usuario único (tú) para entrar al panel admin."""
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)

    @staticmethod
    def set_password(password):
        from werkzeug.security import generate_password_hash
        return generate_password_hash(password)
