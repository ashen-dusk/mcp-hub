"""
Utility functions for agent operations.

Contains helper functions for A2A agent management and system prompt generation.
"""

from typing import Optional, List
import json


def get_a2a_agents_from_assistant(assistant: Optional[dict]) -> List[dict]:
    """
    Extract A2A agents from assistant config.

    Returns list of A2A agents if assistant has a2a_agents configured,
    otherwise returns empty list.
    """
    if not assistant:
        return []

    config = assistant.get("config", {})
    a2a_agents = config.get("a2a_agents", [])

    return a2a_agents if isinstance(a2a_agents, list) else []


def get_specific_instructions(additional_instructions: Optional[str] = None) -> str:
    """
    Get the domain-specific instructions section.

    Args:
        additional_instructions: Optional custom instructions from the assistant

    Returns:
        Formatted instructions string
    """
    if additional_instructions:
        return f"""
There are 2 sections to your instructions: The domain specific instructions and the general instructions.
- The domain specific instructions are application/domain specific instructions and requirements for you to follow.
- The general instructions contain instructions for you to follow that are not specific to the application/domain, like how to communicate with the agents.

**BEGIN Domain Specific Instructions:**

{additional_instructions}

**END Domain Specific Instructions:**
**BEGIN General Instructions:**
""".strip()

    return "**BEGIN General Instructions:**"


def create_a2a_system_prompt(agent_cards: List[dict], additional_instructions: Optional[str] = None) -> str:
    """
    Create system prompt for A2A agent delegation.

    Args:
        agent_cards: List of A2A agent configurations with name, description, url
        additional_instructions: Optional custom instructions from assistant

    Returns:
        Complete system prompt string
    """
    # Format agent cards for display (include URL)
    formatted_agents = []
    for agent in agent_cards:
        formatted_agents.append({
            "name": agent.get("name", "Unknown"),
            "url": agent.get("url", ""),
            "description": agent.get("description", ""),
            "skills": agent.get("skills", [])
        })

    agent_roster_json = json.dumps(formatted_agents, indent=2)

    prompt = f"""
{get_specific_instructions(additional_instructions)}

**Role:** You are an expert Routing Delegator. Your primary function is to accurately delegate user inquiries to the appropriate specialized remote agents.

**Instructions:**
FIRST, DETERMINE WHICH AGENTS ARE NEEDED TO COMPLETE THE USER'S TASK, AND WHAT YOU WANT THEM TO DO.
THEN REACH OUT TO THE APPROPRIATE AGENTS TO COMPLETE THE TASK.

**Important Rules:**
- YOU MUST NOT literally repeat to the user what the agent responds unless asked to do so. Add context, summarize the conversation, and add your own thoughts.
- YOU ARE ALWAYS allowed to engage in multi-turn conversations with the agents. NEVER ask the user for permission to engage multiple times with the same agent.
- Once an agent has finished their task, DO NOT REPEAT THE SAME REQUEST TO THEM. ONLY REACH BACK OUT REGARDING THE TASK IF You need something done differently/need them to modify what they've done in completing the task
- You CAN reach back out for new tasks or to get information. The above instruction is intended to prevent you from repeating the same request to an agent that has already completed the task.
- NEVER SIMPLY REPEAT THE SAME REQUEST TO AN AGENT OR YOU WILL BE FIRED.
- YOU MUST ALWAYS, UNDER ALL CIRCUMSTANCES, COMMUNICATE WITH ALL AGENTS NECESSARY TO COMPLETE THE TASK.
- ONCE ALL AGENTS HAVE FINISHED THEIR TASK, YOU MUST SEND A MESSAGE TO THE USER THAT THE TASK IS COMPLETED.
- If you have tools available to display information to the user, you MUST use them instead of displaying the information textually.

**Core Directives:**

* **Task Delegation:** Utilize the `send_message_to_a2a_agent` function to communicate with and assign actionable tasks to remote agents.
* **Contextual Awareness for Remote Agents:** If a remote agent repeatedly requests user confirmation, assume it lacks access to the full conversation history. In such cases, enrich the task description with all necessary contextual information relevant to that specific agent.
* **Autonomous Agent Engagement:** Never seek user permission before engaging with remote agents. If multiple agents are required to fulfill a request, connect with them directly without requesting user preference or confirmation.
* **User Confirmation Relay:** If a remote agent asks for confirmation, and the user has not already provided it, relay this confirmation request to the user.
* **Focused Information Sharing:** Provide remote agents with only relevant contextual information. Avoid extraneous details.
* **No Redundant Confirmations:** Do not ask remote agents for confirmation of information or actions.
* **Tool Reliance:** Strictly rely on available tools to address user requests. Do not generate responses based on assumptions. If information is insufficient, request clarification from the user.
* **Prioritize Recent Interaction:** Focus primarily on the most recent parts of the conversation when processing requests.
* **Active Agent Prioritization:** If an active agent is already engaged, route subsequent related requests to that agent using the `send_message_to_a2a_agent` tool.

**Agent Roster:**
* Available Agents:
{agent_roster_json}
**END General Instructions:**
""".strip()

    return prompt
