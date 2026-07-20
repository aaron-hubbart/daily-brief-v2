# Used inside the container (see Dockerfile) — NOT the same file as
# gunicorn.conf.py, which binds 127.0.0.1 for the VM/nginx deployment where
# nginx and gunicorn share a host network namespace.
#
# In Kubernetes the container's own network namespace is the isolation
# boundary — binding 0.0.0.0 here is standard and correct; the Service and
# Ingress (or lack of one) control what's actually reachable from outside
# the pod, not this bind address.
bind = '0.0.0.0:8000'
workers = 2
timeout = 120
accesslog = '-'
errorlog = '-'
