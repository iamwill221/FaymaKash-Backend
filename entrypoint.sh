#!/bin/bash
set -e

python manage.py migrate --noinput
exec gunicorn --bind 0.0.0.0:8000 FaymaKashProject.wsgi:application
