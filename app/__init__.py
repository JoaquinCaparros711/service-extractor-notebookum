from flask import Flask
from .config import Config
from .routes.extractions import extractions_bp


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.register_blueprint(extractions_bp)

    @app.route("/health")
    def health_check():
        return {"status": "ok", "service": "extractor"}, 200

    return app
