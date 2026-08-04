FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Capa de dependencias separada del codigo: cambiar un .py no reinstala todo.
COPY pyproject.toml ./
RUN uv pip install --system -r pyproject.toml

COPY settings.py ./
COPY lead_gen/ ./lead_gen/
COPY backend/ ./backend/
COPY nichos/ ./nichos/

RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
