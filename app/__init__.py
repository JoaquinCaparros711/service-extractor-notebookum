from flask import Flask
from flask_cors import CORS
from .config import Config
from .routes.extraction_queries import extraction_queries_bp
from .routes.extractions import extraction_commands_bp
from .routes.strangler import strangler_bp

_CORS_ORIGINS = [
    "https://api.universidad.localhost",
    "http://localhost",
    r"http://localhost:\d+",
    "null",  # file:// pages
]


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    CORS(app, origins=_CORS_ORIGINS, supports_credentials=True)
    app.register_blueprint(extraction_commands_bp)
    app.register_blueprint(extraction_queries_bp)
    app.register_blueprint(strangler_bp)

    @app.route("/health")
    def health_check():
        return {"status": "ok", "service": "extractor"}, 200

    from .utils.consul import register_extractor
    register_extractor()

    return app
