"""Consul service registration — runs once on startup in a background thread."""

import logging
import os
import socket
import threading
import time

import requests

logger = logging.getLogger(__name__)

_CONSUL_URL = os.environ.get("CONSUL_URL", "http://consul:8500")

_EXTRACTOR_TAGS = [
    "traefik.enable=true",
    "traefik.http.routers.extractor.rule=Host(`extractor.universidad.localhost`)",
    "traefik.http.routers.extractor.entryPoints=https",
    "traefik.http.routers.extractor.tls=true",
    "traefik.http.routers.extractor.middlewares=extractor,bulkhead-extractor,cors-extractor",
    "traefik.http.middlewares.cors-extractor.headers.accesscontrolalloworiginlist=*",
    "traefik.http.middlewares.cors-extractor.headers.accesscontrolallowmethods=GET,POST,OPTIONS",
    "traefik.http.middlewares.cors-extractor.headers.accesscontrolallowheaders=Content-Type,Authorization",
    "traefik.http.middlewares.cors-extractor.headers.addvaryheader=true",
    "traefik.http.services.extractor.loadbalancer.server.port=5000",
    "traefik.http.middlewares.extractor.circuitbreaker.expression=NetworkErrorRatio() > 0.5",
    "traefik.http.middlewares.bulkhead-extractor.inflightreq.amount=20",
]


def register_extractor(port: int = 5000) -> None:
    """Register the Extractor service with Consul on startup."""
    _start(service_name="extractor", port=port, tags=_EXTRACTOR_TAGS)


def _start(service_name: str, port: int, tags: list) -> None:
    threading.Thread(
        target=_register_with_retry,
        args=(service_name, port, tags),
        daemon=True,
    ).start()


def _register_with_retry(service_name: str, port: int, tags: list) -> None:
    hostname = socket.gethostname()
    service_id = f"{service_name}-{hostname}"
    payload = {
        "ID": service_id,
        "Name": service_name,
        "Address": hostname,
        "Port": port,
        "Tags": tags,
        "Check": {
            "HTTP": f"http://{hostname}:{port}/health",
            "Interval": "15s",
            "Timeout": "5s",
            "DeregisterCriticalServiceAfter": "30s",
        },
    }

    for attempt in range(10):
        try:
            resp = requests.put(
                f"{_CONSUL_URL}/v1/agent/service/register",
                json=payload,
                timeout=5,
            )
            if resp.status_code == 200:
                logger.info("Registered with Consul as %s", service_id)
                return
            logger.warning("Consul registration HTTP %s", resp.status_code)
        except Exception as exc:
            logger.warning("Consul registration attempt %d failed: %s", attempt + 1, exc)
        time.sleep(5)

    logger.error("Failed to register with Consul after %d attempts", 10)
