"""Expose the src-layout Django ASGI application at Vercel's expected path."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tracereview_web.settings")

from django.core.asgi import get_asgi_application

application = get_asgi_application()
