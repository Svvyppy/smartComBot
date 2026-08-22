FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PADDLE_PDX_CACHE_HOME=/models/paddle

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libgomp1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /models/paddle \
    && chown -R appuser:appuser /models

COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --upgrade pip \
    && python -m pip install \
        --index-url https://www.paddlepaddle.org.cn/packages/stable/cpu/ \
        paddlepaddle==3.0.0 \
    && python -m pip install '.[ocr]'

USER appuser

CMD ["python", "-m", "src.main"]
