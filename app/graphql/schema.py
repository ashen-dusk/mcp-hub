import strawberry

# Import the Query and Mutation classes from your feature-specific schema files
from app.mcp.schema import Query as MCPQuery, Mutation as MCPMutation


@strawberry.type
class Query(MCPQuery):
    # If you had another schema, e.g., for users, you would inherit it here too:
    # class Query(MCPQuery, UserQuery):
    pass


@strawberry.type
class Mutation(MCPMutation):
    # Similarly, you would inherit other mutations here:
    # class Mutation(MCPMutation, UserMutation):
    pass


schema = strawberry.Schema(query=Query, mutation=Mutation)


