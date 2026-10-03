FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SIGNALDESK_DATA=/data \
    SIGNALDESK_CONFIG=/data/config.yaml

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY signaldesk ./signaldesk
COPY config.example.yaml ./

RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app:app /data
USER app

# При первом запуске копируем пример конфигурации в том /data
CMD ["sh", "-c", "[ -f \"$SIGNALDESK_CONFIG\" ] || cp config.example.yaml \"$SIGNALDESK_CONFIG\"; exec python -m signaldesk serve --host 0.0.0.0 --port 8000"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/status')"
