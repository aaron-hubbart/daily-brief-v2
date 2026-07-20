#!/bin/bash
# Azure App Service (Linux, Python runtime) runs this as the site's startup
# command. Set it in Portal: App Service > Configuration > General settings >
# Startup Command, to: bash startup.sh (or paste the gunicorn line directly).
gunicorn --bind=0.0.0.0:8000 --timeout 120 --workers 2 app:app
