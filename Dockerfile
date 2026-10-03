# syntax=docker/dockerfile:1
# Container image for the system under test (the bookshop) only; the test
# framework runs outside the container and talks to it over HTTP.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BOOKSHOP_DB=/data/bookshop.sqlite3

WORKDIR /app

# requirements.txt is exported from uv.lock (runtime dependencies only).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sut ./sut

RUN useradd --uid 1000 --create-home app && mkdir -p /data && chown app:app /data
USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=10 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"

CMD ["uvicorn", "sut.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
