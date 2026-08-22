FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /models/paddle \
    && chown -R appuser:appuser /models

COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --upgrade pip && python -m pip install .

USER appuser

CMD ["python", "-m", "src.main"]

