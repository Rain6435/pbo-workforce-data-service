# syntax=docker/dockerfile:1
#
# One image for the three roles in docker-compose.yml: migrations, the
# importer, and the API. Base images are pinned by version and digest so a
# rebuild cannot silently pick up a different base.

ARG PYTHON_IMAGE=python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

FROM ghcr.io/astral-sh/uv:0.12.20@sha256:100047e74f30778ab704942321a09750d6158739573ff58bf3924085cc6cd2d8 AS uv

# ---- build: resolve the locked dependencies into a virtualenv ------------
FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first, so code changes do not invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Then the package itself, installed (not editable) into the virtualenv.
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# ---- runtime: no build tools, no uv, non-root ----------------------------
FROM ${PYTHON_IMAGE} AS runtime
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app
WORKDIR /app

COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations

USER 10001:10001
EXPOSE 8000

# The API by default; compose overrides the command for migrate and import.
CMD ["uvicorn", "--factory", "pbo_workforce.api.app:create_app", \
     "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
