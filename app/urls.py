from django.urls import path, include
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from strawberry.django.views import AsyncGraphQLView
from app.graphql.schema import schema
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('health/', views.health_check, name='health_check'),

    # OAuth callback endpoint (no trailing slash to match redirect_uri exactly)
    path('oauth-callback', views.oauth_callback, name='oauth_callback'),

    # Audio Transcription endpoint
    path('transcribe/', views.transcribe_audio, name='transcribe_audio'),

    # AG-UI Protocol endpoint
    path(
        "langgraph-agent",
        csrf_exempt(views.agui_langgraph_handler),
        name="agui-langgraph-handler"
    ),

    # GraphQL endpoint
    path(
        "graphql",
        csrf_exempt(AsyncGraphQLView.as_view(schema=schema, graphiql=getattr(settings, "DEBUG", False))),
        name="graphql",
    ),
]
