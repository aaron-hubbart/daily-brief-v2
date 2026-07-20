# Used inside the container (see Dockerfile) — run with:
#   gunicorn -c gunicorn.conf.py app:app
#
# Binds 0.0.0.0, not 127.0.0.1 — in Kubernetes the container's own network
# namespace is the isolation boundary. The Service and Ingress (or lack of
# one) control what's actually reachable from outside the pod, not this
# bind address.
bind = '0.0.0.0:8000'
workers = 2
timeout = 120
accesslog = '-'
errorlog = '-'
