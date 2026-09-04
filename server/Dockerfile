FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Server is stdlib-only: no pip dependencies to install.
COPY server/app.py ./app.py
COPY server/dashboard.html ./dashboard.html

RUN mkdir -p /data/dropbox /data/processed && \
    useradd --system --uid 1001 --create-home board && \
    chown -R board:board /app

ENV DATA_DIR=/data \
    PORT=8734

EXPOSE 8734

USER board

CMD ["python3", "app.py"]
