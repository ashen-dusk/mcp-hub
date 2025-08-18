from django.http import JsonResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

@api_view(['POST'])
def echo_message(request):
    """Simple endpoint that echoes back the message sent in the request body."""
    message = request.data.get('message', 'No message provided')
    return Response({
        "echo": message,
        "received_at": "now",
        "status": "success"
    }, status=status.HTTP_200_OK)

@api_view(['GET'])
def health_check(request):
    """Health check endpoint for monitoring."""
    return Response({
        "status": "healthy",
        "service": "Django CopilotKit Integration",
        "version": "1.0.0"
    }, status=status.HTTP_200_OK)
