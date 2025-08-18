from copilotkit import CopilotKitRemoteEndpoint, LangGraphAgent
from app.agent import graph as search_agent

sdk = CopilotKitRemoteEndpoint(
    agents=lambda context: [
        LangGraphAgent(
            name="search_agent",
            description=(
                "This agent is used to search realtime information using the web search tool."
            ),
            graph=search_agent,
        )
    ],
)


