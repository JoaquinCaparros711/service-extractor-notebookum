from flask import Flask
from .config import Config
from .routes.extraction_queries import extraction_queries_bp
from .routes.extractions import extraction_commands_bp
from .routes.strangler import strangler_bp


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.register_blueprint(extraction_commands_bp)
    app.register_blueprint(extraction_queries_bp)
    app.register_blueprint(strangler_bp)

    @app.route("/health")
    def health_check():
        return {"status": "ok", "service": "extractor"}, 200

    return app
