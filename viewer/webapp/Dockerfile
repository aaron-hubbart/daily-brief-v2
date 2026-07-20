# Build: podman build -t daily-brief-viewer:latest -f viewer/webapp/Dockerfile viewer
# (context is viewer/, not viewer/webapp/, so the image can also copy the
# shared daily-brief-viewer.html from the parent folder — see COPY lines below)
FROM python:3.12-slim

# Non-root user — the app never needs root, and PodSecurityContext/PSA
# policies on most clusters will reject a container that tries to run as root.
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY webapp/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The viewer HTML lives one level up in the repo (viewer/daily-brief-viewer.html)
# and is shared with the local single-user server.py — copy it in rather than
# duplicating it.
COPY daily-brief-viewer.html ./
COPY webapp/app.py webapp/db.py webapp/archive_briefs.py webapp/gunicorn.conf.py ./
COPY webapp/templates/ ./templates/

RUN chown -R appuser:appuser /app

USER appuser

ENV VIEWER_HTML_DIR=/app
EXPOSE 8000
# The CronJob (k8s/cronjob.yaml) overrides this command to run
# archive_briefs.py instead — same image, same dependencies (psycopg2),
# no separate image to build and keep in sync for the archival job.
ENTRYPOINT ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
