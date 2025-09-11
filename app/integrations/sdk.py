from copilotkit import CopilotKitRemoteEndpoint, LangGraphAgent
from app.agent.agent import graph

sdk = CopilotKitRemoteEndpoint(
    agents=lambda context: [
        LangGraphAgent(
            name="mcp-assistant",
            description=(
                "This agent is used to answer questions and perform tasks using the MCP servers."
            ),
            graph=graph,
            langgraph_config={
                "configurable": {
                    "copilotkit_auth": context["properties"].get("authorization")
                }
            }
        ),
    ],
)


