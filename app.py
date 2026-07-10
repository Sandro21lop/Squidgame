from flask import Flask
from flask_login import LoginManager

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
        db.create_all()
        _seed_admin(app)

    return app


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
