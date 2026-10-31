FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    PORT=8000

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app app \
    && mkdir -p /data /var/data \
    && chown app:app /data /var/data

COPY --chown=app:app ./app ./app

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT', '8000'), timeout=2).read()" || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
