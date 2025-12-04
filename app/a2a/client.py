"""
A2A Protocol utilities using the official a2a Python library.
"""

import httpx
import logging
from typing import Dict, Any, Optional
from uuid import uuid4

from a2a.client import A2ACardResolver, A2AClient
from a2a.types import MessageSendParams, SendMessageRequest

logger = logging.getLogger(__name__)


async def validate_a2a_agent_url(agent_url: str) -> Dict[str, Any]:
    """
    Validate an A2A agent URL by fetching its agent card.

    Args:
        agent_url: Base URL of the A2A agent

    Returns:
        Dict containing agent card/metadata if valid

    Raises:
        RuntimeError: If validation fails
    """
    agent_url = agent_url.rstrip('/')
    httpx_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))

    try:
        # Initialize A2ACardResolver with explicit path to agent-card endpoint
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=agent_url,
            agent_card_path='/.well-known/agent-card.json',
        )

        # Fetch public agent card
        logger.info(f"Fetching agent card from: {agent_url}/.well-known/agent-card.json")
        agent_card = await resolver.get_agent_card()
        logger.info(f"Successfully validated A2A agent: {agent_card.name}")

        # Return agent card as dict
        return agent_card.model_dump()

    except Exception as e:
        logger.error(f"Failed to validate A2A agent at {agent_url}: {e}")
        raise RuntimeError(f"Failed to validate A2A agent: {e}")
    finally:
        await httpx_client.aclose()


async def send_a2a_message(
    agent_url: str,
    message: str,
    context_id: Optional[str] = None,
    timeout: int = 60
) -> str:
    """
    Send a message to an A2A agent using the official a2a library.

    Args:
        agent_url: Base URL of the A2A agent
        message: The message/task to send to the agent
        context_id: Optional context ID for conversation continuity
        timeout: Request timeout in seconds

    Returns:
        String response from the agent

    Raises:
        RuntimeError: If communication fails
    """
    agent_url = agent_url.rstrip('/')
    httpx_client = httpx.AsyncClient(timeout=httpx.Timeout(float(timeout)))

    try:
        # Initialize A2ACardResolver and get agent card
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=agent_url,
            agent_card_path='/.well-known/agent-card.json',
        )

        logger.info(f"Fetching agent card from: {agent_url}")
        agent_card = await resolver.get_agent_card()

        # Initialize A2A client
        a2a_client = A2AClient(
            httpx_client=httpx_client,
            agent_card=agent_card
        )

        # Prepare A2A request payload
        send_message_payload = {
            'message': {
                'role': 'user',
                'parts': [
                    {'kind': 'text', 'text': message}
                ],
                'message_id': uuid4().hex,
            },
        }

        # Add context_id if provided for conversation continuity
        if context_id:
            send_message_payload['message']['context_id'] = context_id

        # Send request to A2A server
        request = SendMessageRequest(
            id=str(uuid4()),
            params=MessageSendParams(**send_message_payload)
        )

        logger.info(f"Sending message to A2A agent: {agent_card.name}")
        response = await a2a_client.send_message(request)
        logger.info(f"Response from A2A agent: {response}")
        # Check if response has root
        if not hasattr(response, 'root') or not response.root:
            logger.error("Response missing 'root' attribute")
            raise RuntimeError("Invalid response format from A2A server")

        # Check if root is an error response
        if hasattr(response.root, 'error') and response.root.error:
            logger.error(f"A2A server error: {response.root.error}")
            raise RuntimeError(f"A2A Server Error: {response.root.error}")

        # Check if root has result (success response)
        if not hasattr(response.root, 'result') or not response.root.result:
            logger.error("Response missing 'result' attribute")
            raise RuntimeError("Invalid response format from A2A server")

        # Extract response data
        result = response.root.result

        # 1. Check for 'parts' (Message structure)
        if hasattr(result, 'parts') and result.parts:
            # Iterate through parts to find text content
            content_parts = []
            for part in result.parts:
                # Check if part has root and text (TextPart)
                if hasattr(part, 'root'):
                    if hasattr(part.root, 'text'):
                        content_parts.append(part.root.text)
                    elif hasattr(part.root, 'content'):
                        content_parts.append(part.root.content)
                # Direct attribute check (fallback)
                elif hasattr(part, 'text'):
                    content_parts.append(part.text)
                elif hasattr(part, 'content'):
                    content_parts.append(part.content)
            
            if content_parts:
                full_content = "\n".join(content_parts)
                logger.info(f"Successfully retrieved response from A2A server (via parts)")
                return full_content

        # 2. Check for 'artifacts' (Legacy/Alternative structure)
        if hasattr(result, 'artifacts') and result.artifacts:
            artifact = result.artifacts[0]
            if hasattr(artifact, 'parts') and artifact.parts:
                part = artifact.parts[0]
                if hasattr(part, 'root') and hasattr(part.root, 'text'):
                    content = part.root.text
                    logger.info(f"Successfully retrieved response from A2A server (via artifacts)")
                    return content

        # 3. Fallback: check for content in other locations
        if hasattr(result, 'content') and result.content:
            logger.info(f"Successfully retrieved response from A2A server (via content)")
            return result.content

        logger.warning(f"No content found in A2A server response. Result keys: {result.__dict__.keys() if hasattr(result, '__dict__') else 'unknown'}")
        return "No response content received from A2A server"

    except Exception as e:
        logger.error(f"Error communicating with A2A server: {e}")
        raise RuntimeError(f"Failed to communicate with A2A agent: {e}")
    finally:
        await httpx_client.aclose()
