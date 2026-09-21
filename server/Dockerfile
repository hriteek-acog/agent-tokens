FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Server is stdlib-only: no pip dependencies to install.
COPY server/app.py ./app.py
COPY server/dashboard.html ./dashboard.html
COPY server/logo.png ./logo.png

# NOTE: runs as root ON PURPOSE. The dropbox is mode 1733 (create-only for
# everyone else): only root (or the dir owner) can list/read/unlink all
# submissions for ingest. A non-root server user could never see drop files.
# The trust boundary is the LDAP-gated reverse proxy + labels, not the uid.

ENV DATA_DIR=/data \
    PORT=8734

EXPOSE 8734

CMD ["python3", "app.py"]
