FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MALLOC_ARENA_MAX=2 MALLOC_MMAP_THRESHOLD_=131072
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin emby
COPY master/ /app/master/
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"
CMD ["python", "-m", "uvicorn", "master.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--limit-concurrency", "128", "--timeout-keep-alive", "5", "--timeout-graceful-shutdown", "45", "--no-access-log"]
