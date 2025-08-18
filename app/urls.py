from django.urls import path
from . import views
from .copilotkit_integration import copilotkit_handler
from .sdk import sdk

urlpatterns = [
    # copilotkit endpoints
    path("copilotkit/<path:path>", copilotkit_handler, name="copilotkit-path"),

    # DRF views
    path("echo", views.echo_message, name="echo_message"),
    path("health", views.health_check, name="health_check"),
]
