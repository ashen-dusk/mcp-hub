import json
import os
from django.utils.timezone import now
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from ag_ui_langgraph.agent import LangGraphAgent
from ag_ui.encoder import EventEncoder
from ag_ui.core import RunAgentInput
from app.agent.agent import graph
from openai import OpenAI


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
# Note: needs to be protected
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
            content_type=encoder.get_content_type()
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


# ============================================================================
# Audio Transcription Endpoint
# ============================================================================
# Note: needs to be protected
@csrf_exempt
def transcribe_audio(request):
    """
    Transcribe audio using OpenAI Whisper API

    Endpoint: POST /api/transcribe

    Accepts audio file and returns transcribed text.
    """
    if request.method != 'POST':
        return JsonResponse(
            {"error": "Method not allowed. Use POST."},
            status=405
        )

    try:
        # Check if audio file is provided (accept both 'audio' and 'file' keys)
        print(f"Request FILES: {request.FILES}")

        if 'audio' in request.FILES:
            audio_file = request.FILES['audio']
        elif 'file' in request.FILES:
            audio_file = request.FILES['file']
        else:
            return JsonResponse(
                {"error": "No audio file provided. Please upload an audio file with key 'audio' or 'file'."},
                status=400
            )

        # Validate file size (max 25MB for Whisper API)
        max_size = 25 * 1024 * 1024  # 25MB in bytes
        if audio_file.size > max_size:
            return JsonResponse(
                {"error": f"File too large. Maximum size is 25MB, got {audio_file.size / (1024*1024):.2f}MB"},
                status=400
            )

        # Get OpenAI API key from environment
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            return JsonResponse(
                {"error": "OpenAI API key not configured on server"},
                status=500
            )

        # Initialize OpenAI client
        client = OpenAI(api_key=api_key)

        # Get optional parameters from request
        language = request.POST.get('language', None)  # Optional: ISO-639-1 language code
        prompt = request.POST.get('prompt', None)  # Optional: context/spelling guide

        # Convert Django uploaded file to a format OpenAI expects
        # OpenAI expects a tuple: (filename, file_content, content_type)
        file_content = audio_file.read()
        file_tuple = (audio_file.name, file_content, audio_file.content_type)

        # Transcribe using Whisper API
        transcription_params = {
            'file': file_tuple,
            'model': 'whisper-1',
        }

        if language:
            transcription_params['language'] = language

        if prompt:
            transcription_params['prompt'] = prompt

        transcription = client.audio.transcriptions.create(**transcription_params)

        # Return transcribed text
        return JsonResponse({
            "success": True,
            "text": transcription.text,
            "language": language if language else "auto-detected"
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse(
            {"error": "Transcription failed", "details": str(e)},
            status=500
        )