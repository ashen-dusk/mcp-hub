from copilotkit import CopilotKitRemoteEndpoint, LangGraphAgent
from app.agent.agent import graph

sdk = CopilotKitRemoteEndpoint(
    agents=lambda context: [
        LangGraphAgent(
            name="medi_aid",
            description=(
                "This agent is used to search realtime information using the web search tool."
            ),
            graph=graph,
        ),
    ],
)


