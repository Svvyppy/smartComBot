FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PADDLE_PDX_CACHE_HOME=/models/paddle \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libgomp1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /models/paddle \
    && chown -R appuser:appuser /models

RUN python -m pip install --upgrade pip \
    && python -m pip install \
        --index-url https://www.paddlepaddle.org.cn/packages/stable/cpu/ \
        paddlepaddle==3.0.0

COPY pyproject.toml ./
RUN mkdir -p src \
    && touch src/__init__.py \
    && python -m pip install '.[ocr]' \
    && rm -rf src utility_meter_bot.egg-info

COPY src ./src
RUN python -m pip install --no-deps .

USER appuser

CMD ["python", "-m", "src.main"]
