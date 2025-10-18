import json
from django.utils.timezone import now
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from ag_ui_langgraph.agent import LangGraphAgent
from ag_ui.encoder import EventEncoder 
from ag_ui.core import RunAgentInput
from app.agent.agent import graph


def home(request):
    return HttpResponse("MCP Hub is running 🚀")

def health_check(request):
    data = {
        "status": "ok",
        "timestamp": now().isoformat(),
        "message": "Service is healthy"
    }
    return JsonResponse(data)

# ============================================================================
# Django View Handler
# ============================================================================
# Initialize the agent instance
async def agui_langgraph_handler(request):
    """
    Pure Django async view handler for AG-UI protocol

    Endpoint: POST /langgraph-agent

    Accepts RunAgentInput and streams AG-UI protocol events via SSE.
    """
    try:
        agent = LangGraphAgent(name="mcpAssistant", description="Agent for mcp's", graph=graph)
        
        # Parse request body
        body_bytes = request.body
        body = json.loads(body_bytes.decode('utf-8'))
        encoder = EventEncoder()

        # Validate input with Pydantic
        input_data = RunAgentInput(**body)

        # Create async generator for streaming
        async def event_generator():
            # Pass only input_data (agent.run takes only 1 argument besides self)
            async for event in agent.run(input_data):
                yield encoder.encode(event)

        # Use async streaming response
        response = StreamingHttpResponse(
            streaming_content=event_generator(),
            content_type=encoder.content_type()
        )

        # Set SSE headers
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        response['Connection'] = 'keep-alive'

        return response

    except json.JSONDecodeError as e:
        return JsonResponse(
            {"error": "Invalid JSON", "details": str(e)},
            status=400
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse(
            {"error": "Internal server error", "details": str(e)},
            status=500
        )