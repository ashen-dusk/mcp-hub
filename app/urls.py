from django.urls import path, include
from django.conf import settings
from .copilotkit_integration import copilotkit_handler
from strawberry.django.views import AsyncGraphQLView
from .graphql import schema

urlpatterns = [
    path("copilotkit/<path:path>", copilotkit_handler, name="copilotkit-path"),
    path(
        "graphql",
        AsyncGraphQLView.as_view(schema=schema, graphiql=getattr(settings, "DEBUG", False)),
        name="graphql",
    ),
]
