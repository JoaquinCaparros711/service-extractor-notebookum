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
