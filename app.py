from flask import Flask
from flask_login import LoginManager
from sqlalchemy import inspect, text

from config import Config
from extensions import db, login_manager
from models import AdminUser


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)

    from routes.public import public_bp
    from routes.webhooks import webhooks_bp
    from routes.api import api_bp
    from routes.admin import admin_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)

    @login_manager.user_loader
    def load_user(user_id):
        return AdminUser.query.get(int(user_id))

    with app.app_context():
        _fix_legacy_schema()
        db.create_all()
        _seed_admin(app)

    return app


def _fix_legacy_schema():
    """Arreglo de una sola vez: si la tabla `subscriptions` quedó de una
    versión vieja del proyecto (Lemon Squeezy) sin la columna
    `paypal_subscription_id`, la borramos junto con las tablas relacionadas
    para que `db.create_all()` las vuelva a crear con el esquema actual
    (PayPal). No hay datos reales que perder: si esta migración corre es
    porque esas tablas eran de antes de tener ventas de verdad.
    Es seguro dejar esto corriendo en cada arranque: una vez que el
    esquema ya está al día, no hace nada."""
    inspector = inspect(db.engine)
    if "subscriptions" not in inspector.get_table_names():
        return

    columnas = {c["name"] for c in inspector.get_columns("subscriptions")}
    if "paypal_subscription_id" in columnas:
        return  # ya está al día, no hacer nada

    with db.engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS licenses CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS subscriptions CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS customers CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS webhook_events CASCADE"))
        conn.commit()
    print("[app] Tablas viejas (esquema Lemon Squeezy) eliminadas; se recrean con el esquema de PayPal.")


def _seed_admin(app):
    """Crea (o actualiza la contraseña de) el usuario admin a partir de
    las variables de entorno ADMIN_EMAIL / ADMIN_PASSWORD."""
    email = app.config["ADMIN_EMAIL"].strip().lower()
    password = app.config["ADMIN_PASSWORD"]

    user = AdminUser.query.filter_by(email=email).first()
    if not user:
        user = AdminUser(email=email, password_hash=AdminUser.set_password(password))
        db.session.add(user)
        db.session.commit()


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)