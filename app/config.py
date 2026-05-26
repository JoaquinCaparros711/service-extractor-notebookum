import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    MAX_UPLOAD_SIZE = int(os.environ.get("MAX_UPLOAD_SIZE", 26214400))  # 25MB
    HEAVY_PDF_THRESHOLD_BYTES = int(os.environ.get("HEAVY_PDF_THRESHOLD_BYTES", 5242880))
    LIGHT_BULKHEAD_WORKERS = int(os.environ.get("LIGHT_BULKHEAD_WORKERS", 2))
    HEAVY_BULKHEAD_WORKERS = int(os.environ.get("HEAVY_BULKHEAD_WORKERS", 2))
    LIGHT_BULKHEAD_CAPACITY = int(os.environ.get("LIGHT_BULKHEAD_CAPACITY", 20))
    HEAVY_BULKHEAD_CAPACITY = int(os.environ.get("HEAVY_BULKHEAD_CAPACITY", 5))
    RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", 60))
    RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", 60))
    RATE_LIMIT_CLIENT_HEADER = os.environ.get("RATE_LIMIT_CLIENT_HEADER", "X-Client-ID")
    STRANGLER_CONTRACT_VERSION = os.environ.get("STRANGLER_CONTRACT_VERSION", "v1")
    STRANGLER_MONOLITH_CLIENT_ID = os.environ.get(
        "STRANGLER_MONOLITH_CLIENT_ID",
        "notebookum-monolith",
    )
    DOCLING_CIRCUIT_FAILURE_THRESHOLD = int(
        os.environ.get("DOCLING_CIRCUIT_FAILURE_THRESHOLD", 3)
    )
    DOCLING_CIRCUIT_RESET_SECONDS = float(
        os.environ.get("DOCLING_CIRCUIT_RESET_SECONDS", 30)
    )
