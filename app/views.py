from django.http import HttpResponse, JsonResponse
from django.utils.timezone import now

def home(request):
    return HttpResponse("MCP Hub is running 🚀")

def health_check(request):
    data = {
        "status": "ok",
        "timestamp": now().isoformat(),
        "message": "Service is healthy"
    }
    return JsonResponse(data)
