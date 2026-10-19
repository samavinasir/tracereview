"""Expose the src-layout Django WSGI application at Vercel's expected path."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tracereview_web.settings")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
