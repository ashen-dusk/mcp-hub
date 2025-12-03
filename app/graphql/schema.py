import strawberry

# import the Query and Mutation classes from your feature-specific schema files
from app.mcp.mcp_schema import Query as MCPQuery, Mutation as MCPMutation
from app.mcp.category_schema import Query as CategoryQuery, Mutation as CategoryMutation
from app.auth.schema import AuthQuery
from app.assistant_schema import Query as AssistantQuery, Mutation as AssistantMutation
from app.a2a.schema import Query as A2AQuery, Mutation as A2AMutation


@strawberry.type
# ── graphql: root query ───────────────────────────────────────────────────────
class Query(MCPQuery, CategoryQuery, AuthQuery, AssistantQuery, A2AQuery):
    pass


@strawberry.type
# ── graphql: root mutation ───────────────────────────────────────────────────
class Mutation(MCPMutation, CategoryMutation, AssistantMutation, A2AMutation):
    pass


schema = strawberry.Schema(query=Query, mutation=Mutation)


