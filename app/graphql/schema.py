import strawberry

# import the Query and Mutation classes from your feature-specific schema files
from app.mcp.mcp_schema import Query as MCPQuery, Mutation as MCPMutation
from app.auth.schema import AuthQuery


@strawberry.type
# ── graphql: root query ───────────────────────────────────────────────────────
class Query(MCPQuery, AuthQuery):
    pass


@strawberry.type
# ── graphql: root mutation ───────────────────────────────────────────────────
class Mutation(MCPMutation):
    pass


schema = strawberry.Schema(query=Query, mutation=Mutation)


