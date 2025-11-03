import json
import os
import logging
import asyncio
from urllib.parse import urlencode
from django.utils.timezone import now
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from ag_ui_langgraph.agent import LangGraphAgent
from ag_ui.encoder import EventEncoder
from ag_ui.core import RunAgentInput
from app.agent.agent import graph
from openai import OpenAI
from app.mcp.redis_manager import mcp_redis
from app.mcp.models import MCPServer
from app.mcp.manager import mcp
from app.mcp.oauth_helper import exchange_authorization_code
from copilotkit import LangGraphAGUIAgent
from app.agent.plan_and_execute import plan_and_execute_graph
# from ag_ui_langgraph.agent import LangGraphAgent
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
# OAuth Callback Endpoint
# ============================================================================
@csrf_exempt
async def oauth_callback(request):
    """
    Handle OAuth callback from OAuth providers.

    Endpoint: GET /api/oauth-callback?code=...&state=...

    This endpoint:
    1. Receives authorization code and state from OAuth provider
    2. Retrieves server info from Redis using state
    3. Exchanges code for access tokens
    4. Stores tokens in user-isolated file storage
    5. Connects to MCP server and fetches tools
    6. Updates Redis with connection status
    7. Redirects to frontend success page
    """
    try:
        # Extract query parameters
        code = request.GET.get('code')
        state = request.GET.get('state')
        error = request.GET.get('error')
        error_description = request.GET.get('error_description', '')

        logging.info(f"[OAuth Callback] Received callback - state: {state[:8] if state else 'None'}..., error: {error}")

        # Handle OAuth errors
        if error:
            logging.error(f"[OAuth Callback] OAuth error: {error} - {error_description}")
            frontend_url = os.getenv('NEXT_PUBLIC_APP_URL', 'http://localhost:3000')
            error_params = urlencode({
                'error': error,
                'error_description': error_description
            })
            return HttpResponseRedirect(f"{frontend_url}/mcp?{error_params}")

        # Validate required parameters
        if not code or not state:
            logging.error(f"[OAuth Callback] Missing required parameters - code: {bool(code)}, state: {bool(state)}")
            return JsonResponse({
                "error": "Missing required parameters: code and state"
            }, status=400)

        # Retrieve OAuth session data from Redis
        oauth_session = await mcp_redis.get_oauth_session(state)
        if not oauth_session:
            logging.error(f"[OAuth Callback] OAuth session not found for state: {state[:8]}...")
            return JsonResponse({
                "error": "OAuth session not found or expired. Please try connecting again."
            }, status=404)

        server_name = oauth_session.get('server_name')
        session_id = oauth_session.get('session_id')
        user_id = oauth_session.get('user_id')

        logging.info(f"[OAuth Callback] Processing OAuth for server: {server_name}, session: {session_id}")

        # Trigger background task to complete OAuth flow
        # We do this in background so we can immediately redirect the user
        asyncio.create_task(
            handle_token_exchange(
                server_name=server_name,
                session_id=session_id,
                user_id=user_id,
                code=code,
                state=state
            )
        )

        # Redirect to frontend MCP page
        frontend_url = os.getenv('NEXT_PUBLIC_APP_URL', 'http://localhost:3000')
        success_params = urlencode({
            'server': server_name,
            'step': 'success'
        })
        redirect_url = f"{frontend_url}/mcp?{success_params}"

        logging.info(f"[OAuth Callback] Redirecting to: {redirect_url}")

        return HttpResponseRedirect(redirect_url)

    except Exception as e:
        logging.exception(f"[OAuth Callback] Unexpected error: {e}")
        return JsonResponse({
            "error": "Internal server error",
            "details": str(e)
        }, status=500)

async def handle_token_exchange(
    server_name: str,
    session_id: str,
    user_id: str,
    code: str,
    state: str
):
    """
    Complete the OAuth flow in background.

    This function:
    1. Exchanges authorization code for access tokens
    2. Stores tokens in file storage
    3. Connects to MCP server
    4. Fetches tools
    5. Updates Redis with connection status
    """
    try:
        logging.info(f"[OAuth Flow] Starting background OAuth completion for server: {server_name}")

        # Get server from database
        try:
            server = await MCPServer.objects.aget(name=server_name)
        except MCPServer.DoesNotExist:
            logging.error(f"[OAuth Flow] Server not found: {server_name}")
            await mcp_redis.set_connection_status(
                server_name,
                "FAILED",
                [],
                session_id
            )
            return

        # Step 1: Exchange authorization code for tokens
        success, message = await exchange_authorization_code(
            server=server,
            code=code,
            session_id=session_id,
            user_id=user_id
        )

        if not success:
            logging.error(f"[OAuth Flow] Token exchange failed: {message}")
            await mcp_redis.set_connection_status(
                server_name,
                "FAILED",
                [],
                session_id
            )
            return

        logging.info(f"[OAuth Flow] ✅ Tokens exchanged successfully")

        # Step 2: Connect to MCP server and fetch tools
        success, message, connected_server = await mcp.connect_server(
            name=server_name,
            session_id=session_id
        )

        if success:
            logging.info(f"[OAuth Flow] ✅ Successfully connected to {server_name}")
            logging.info(f"[OAuth Flow] Fetched {len(connected_server.tools) if connected_server else 0} tools")
        else:
            logging.error(f"[OAuth Flow] ❌ Failed to connect to {server_name}: {message}")

    except Exception as e:
        logging.exception(f"[OAuth Flow] Error completing OAuth flow for {server_name}: {e}")
        await mcp_redis.set_connection_status(
            server_name,
            "FAILED",
            [],
            session_id
        )

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
        agent = LangGraphAGUIAgent(name="mcpAssistant", description="Agent for mcp's", graph=plan_and_execute_graph)
        
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