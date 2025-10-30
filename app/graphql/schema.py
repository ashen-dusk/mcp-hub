import strawberry

# import the Query and Mutation classes from your feature-specific schema files
from app.mcp.mcp_schema import Query as MCPQuery, Mutation as MCPMutation
from app.mcp.category_schema import Query as CategoryQuery, Mutation as CategoryMutation
from app.auth.schema import AuthQuery
from app.assistant_schema import Query as AssistantQuery, Mutation as AssistantMutation


@strawberry.type
# ── graphql: root query ───────────────────────────────────────────────────────
class Query(MCPQuery, CategoryQuery, AuthQuery, AssistantQuery):
    pass


@strawberry.type
# ── graphql: root mutation ───────────────────────────────────────────────────
class Mutation(MCPMutation, CategoryMutation, AssistantMutation):
    pass


schema = strawberry.Schema(query=Query, mutation=Mutation)


