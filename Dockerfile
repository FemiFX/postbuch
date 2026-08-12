FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential poppler-utils tesseract-ocr tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
RUN pip install --upgrade pip && pip install -e .[dev]

COPY . /app

FROM base AS web
CMD ["uvicorn", "postbuch.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS worker
CMD ["python", "-m", "postbuch.worker.main"]

