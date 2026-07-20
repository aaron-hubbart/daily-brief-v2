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
COPY webapp/app.py ./
COPY webapp/gunicorn.k8s.conf.py ./gunicorn.conf.py

# data/ is where per-user brief files land — mounted from a PVC in
# Kubernetes (see k8s/*.yaml), not baked into the image. Create it here only
# so local `docker run` without a volume still works for a quick smoke test.
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

ENV VIEWER_HTML_DIR=/app
EXPOSE 8000
ENTRYPOINT ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
