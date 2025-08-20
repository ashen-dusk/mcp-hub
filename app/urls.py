from django.urls import path, include
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from .integrations.copilotkit_integration import copilotkit_handler
from strawberry.django.views import AsyncGraphQLView
from app.graphql.schema import schema

urlpatterns = [
    path(
        "copilotkit/<path:path>", 
        csrf_exempt(copilotkit_handler), 
        name="copilotkit-path"
    ),
    path(
        "graphql",
        csrf_exempt(AsyncGraphQLView.as_view(schema=schema, graphiql=getattr(settings, "DEBUG", False))),
        name="graphql",
    ),
]
