"""
ASGI config for assistant project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application
from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'assistant.settings')

django_asgi_app = get_asgi_application()

# when running under an ASGI server (e.g., uvicorn) we need to serve static files manually
# in production, we can use a CDN or a static file server like nginx
if getattr(settings, "DEBUG", False):
    application = ASGIStaticFilesHandler(django_asgi_app)
else:
    application = django_asgi_app
