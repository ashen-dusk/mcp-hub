import re
import uuid
import json
import logging
import inspect
from typing import List, Optional, Any, cast

from django.http import JsonResponse, StreamingHttpResponse
from copilotkit.types import Message, MetaEvent
from copilotkit import CopilotKitRemoteEndpoint, CopilotKitContext
from copilotkit.exc import (
    ActionNotFoundException,
    ActionExecutionException,
    AgentNotFoundException,
    AgentExecutionException,
)
from copilotkit.action import ActionDict
from .sdk import sdk

logger = logging.getLogger(__name__)

def get_context(request, body):
    return cast(
        CopilotKitContext,
        {
            "properties": (body or {}).get("properties", {}),
            "frontend_url": (body or {}).get("frontendUrl", None),
            "headers": request.headers,
        },
    )

def body_get_or_raise(body: Any, key: str):
    value = body.get(key)
    if value is None:
        return JsonResponse({"error": f"{key} is required"}, status=400)
    return value

async def copilotkit_handler(request, path=""):
    try:
        body = json.loads(request.body.decode()) if request.body else {}
    except Exception as e:
        logger.error(f"Failed to parse request body: {e}")
        body = {}

    method = request.method.upper()
    context = get_context(request, body)

    print('path is - ', path)
    # ----------------- /info -----------------
    if method in ["GET", "POST"] and path in ["", "info", "info/"]:
        return await handle_info(sdk=sdk, context=context, as_html=False)

    # ----------------- /agent/<name> -----------------
    if method == "POST" and (match := re.match(r"agent/([a-zA-Z0-9_-]+)$", path)):
        name = match.group(1)
        thread_id = body.get("threadId", str(uuid.uuid4()))
        state = body.get("state", {})
        messages = body.get("messages", [])
        actions = body.get("actions", [])
        node_name = body.get("nodeName")

        return handle_execute_agent(
            sdk=sdk,
            context=context,
            thread_id=thread_id,
            name=name,
            state=state,
            config=body.get("config"),
            messages=messages,
            actions=actions,
            node_name=node_name,
            meta_events=body.get("metaEvents", []),
        )

    # ----------------- /agent/<name>/state -----------------
    if method == "POST" and (match := re.match(r"agent/([a-zA-Z0-9_-]+)/state$", path)):
        name = match.group(1)
        thread_id = body_get_or_raise(body, "threadId")
        return await handle_get_agent_state(sdk=sdk, context=context, thread_id=thread_id, name=name)

    # ----------------- /action/<name> -----------------
    if method == "POST" and (match := re.match(r"action/([a-zA-Z0-9_-]+)$", path)):
        name = match.group(1)
        arguments = body.get("arguments", {})
        return await handle_execute_action(sdk=sdk, context=context, name=name, arguments=arguments)
    
    # ----------------- v1 compatibility -----------------
    result_v1 = await handler_v1(
        sdk=sdk,
        method=method,
        path=path,
        body=body,
        context=context,
    )
    if result_v1 is not None:
        return result_v1

    return JsonResponse({"error": "Not found"}, status=404)

async def handler_v1(
        sdk: CopilotKitRemoteEndpoint,
        method: str,
        path: str,
        body: Any,
        context: CopilotKitContext,
    ):
    """Handle FastAPI request for v1"""

    if body is None:
        return JsonResponse({"error": "Request body is required"}, status=400)

        # raise HTTPException(status_code=400, detail="Request body is required")

    if method == 'POST' and path == 'info':
        return await handle_info(sdk=sdk, context=context)


    if method == 'POST' and path == 'actions/execute':
        name = body_get_or_raise(body, "name")
        arguments = body.get("arguments", {})

        return await handle_execute_action(
            sdk=sdk,
            context=context,
            name=name,
            arguments=arguments,
        )

    if method == 'POST' and path == 'agents/execute':
        thread_id = body.get("threadId")
        node_name = body.get("nodeName")
        config = body.get("config")

        name = body_get_or_raise(body, "name")
        state = body_get_or_raise(body, "state")
        messages = body_get_or_raise(body, "messages")
        actions = cast(List[ActionDict], body.get("actions", []))
        meta_events = cast(List[MetaEvent], body.get("metaEvents", []))

        return handle_execute_agent(
            sdk=sdk,
            context=context,
            thread_id=thread_id,
            node_name=node_name,
            name=name,
            state=state,
            config=config,
            messages=messages,
            actions=actions,
            meta_events=meta_events,
        )


    if method == 'POST' and path == 'agents/state':
        thread_id = body_get_or_raise(body, "threadId")
        name = body_get_or_raise(body, "name")

        return await handle_get_agent_state(
            sdk=sdk,
            context=context,
            thread_id=thread_id,
            name=name,
        )

    return None

# ---------------------------------------------------------------------
# Handlers ( Handlers are the same as FastAPI, ported to Django)
# ---------------------------------------------------------------------
async def handle_info(*, sdk, context, as_html=False):
    result = sdk.info(context=context)
    return JsonResponse(result, status=200)

async def handle_execute_action(sdk, context, name: str, arguments: dict):
    try:
        result = await sdk.execute_action(
            context=context,
            name=name,
            arguments=arguments
        )
        return JsonResponse(result, status=200)
    except ActionNotFoundException as exc:
        logger.error("Action not found: %s", exc)
        return JsonResponse({"error": str(exc)}, status=404)
    except ActionExecutionException as exc:
        logger.error("Action execution error: %s", exc)
        return JsonResponse({"error": str(exc)}, status=500)
    except Exception as exc:
        logger.exception("Action execution error")
        return JsonResponse({"error": str(exc)}, status=500)

def handle_execute_agent(
    *,
    sdk,
    context,
    thread_id: str,
    name: str,
    state: dict,
    config: Optional[dict],
    messages: List[Message],
    actions: List[dict],
    node_name: Optional[str],
    meta_events: Optional[List[MetaEvent]] = None,
):
    try:
        events = sdk.execute_agent(
            context=context,
            thread_id=thread_id,
            name=name,
            node_name=node_name,
            state=state,
            config=config,
            messages=messages,
            actions=actions,
            meta_events=meta_events,
        )
        return StreamingHttpResponse(events, content_type="application/json")
    except AgentNotFoundException as exc:
        logger.error("Agent not found: %s", exc)
        return JsonResponse({"error": str(exc)}, status=404)
    except AgentExecutionException as exc:
        logger.error("Agent execution error: %s", exc)
        return JsonResponse({"error": str(exc)}, status=500)
    except Exception as exc:
        logger.exception("Agent execution error")
        return JsonResponse({"error": str(exc)}, status=500)

async def handle_get_agent_state(*, sdk, context, thread_id: str, name: str):
    try:
        result = await sdk.get_agent_state(
            context=context,
            thread_id=thread_id,
            name=name,
        )
        return JsonResponse(result, status=200)
    except AgentNotFoundException as exc:
        logger.error("Agent not found: %s", exc)
        return JsonResponse({"error": str(exc)}, status=404)
    except Exception as exc:
        logger.exception("Agent get state error")
        return JsonResponse({"error": str(exc)}, status=500)

