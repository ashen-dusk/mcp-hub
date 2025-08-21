import strawberry

# import the Query and Mutation classes from your feature-specific schema files
from app.mcp.mcp_schema import Query as MCPQuery, Mutation as MCPMutation


@strawberry.type
# ── graphql: root query ───────────────────────────────────────────────────────
class Query(MCPQuery):
    # if you had another schema, e.g., for users, you would inherit it here too:
    # class Query(MCPQuery, UserQuery):
    pass


@strawberry.type
# ── graphql: root mutation ───────────────────────────────────────────────────
class Mutation(MCPMutation):
    # similarly, you would inherit other mutations here:
    # class Mutation(MCPMutation, UserMutation):
    pass


schema = strawberry.Schema(query=Query, mutation=Mutation)


