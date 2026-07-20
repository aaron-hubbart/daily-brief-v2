# Run with: gunicorn -c gunicorn.conf.py app:app
# Binds to localhost only — nginx is the only thing that should ever talk to
# this process directly. Never bind this to 0.0.0.0 on a host that also runs
# other public-facing services without a firewall rule backing it up.
bind = '127.0.0.1:8000'
workers = 2
timeout = 120
accesslog = '-'
errorlog = '-'
