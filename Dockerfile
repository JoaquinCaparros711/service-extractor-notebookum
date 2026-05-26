FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

COPY pyproject.toml uv.lock* ./

RUN uv sync

COPY . .

EXPOSE 5000

CMD ["uv", "run", "granian", "--interface", "wsgi", "main:app", "--host", "0.0.0.0", "--port", "5000", "--workers", "2"]
