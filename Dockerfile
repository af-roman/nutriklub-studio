FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STUDIO_HOST=0.0.0.0 \
    STUDIO_PORT=8000 \
    STUDIO_DATA=/data

COPY pyproject.toml README.md ./
COPY studio ./studio

RUN pip install --no-cache-dir .

RUN mkdir -p /data

EXPOSE 8000

CMD ["studio"]
