FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# opencv-python-headless still needs glib at runtime even in the headless build.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies before copying the code so source edits don't invalidate
# the (slow) dependency layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src

# Shell form so $PORT is expanded (Railway sets it; the VPS compose passes it in).
# Card generation is CPU-bound (Pillow + OpenCV face detection); a couple of
# workers with threads serves concurrent card + analyse requests without pinning
# a single process.
CMD ["sh", "-c", "gunicorn --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:${PORT:-5002} app.main:app"]
