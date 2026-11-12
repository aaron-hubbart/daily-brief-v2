# Used inside the container (see Dockerfile) — run with:
#   gunicorn -c gunicorn.conf.py app:app
#
# Binds 0.0.0.0, not 127.0.0.1 — in Kubernetes the container's own network
# namespace is the isolation boundary. The Service and Ingress (or lack of
# one) control what's actually reachable from outside the pod, not this
# bind address.
bind = '0.0.0.0:8000'
workers = 2
# The brief view fires several section requests in parallel (see
# brief_fragment.html's progressive section loading) and each one blocks
# on an external API call (Slack/Asana/Google Drive). With sync workers,
# those alone saturate both workers and queue out any other request —
# including the Day Plan/Account Health navigation — until they finish.
# gthread lets each worker serve several of these I/O-bound requests
# concurrently instead of one at a time.
worker_class = 'gthread'
threads = 8
timeout = 120
accesslog = '-'
errorlog = '-'
