# Simplified Plan-and-Execute Pattern

## Overview

This implementation follows the LangGraph tutorial pattern for plan-and-execute agents. It's intentionally simplified compared to the previous complex architecture.

## Architecture

The simplified architecture has 4 main nodes:

```
START → plan → execute_step → [tools?] → execute_step → ... → END
                                   ↓
                              [replan if needed]
```

### Nodes

1. **plan_node**: Creates a simple list of steps from user request
2. **execute_step_node**: Executes one step at a time
3. **tool_execution_node**: Handles tool calls when needed
4. **replan_node**: Optionally adjusts plan if failures occur

### Routing

- After each step execution, check if:
  - Tools are needed → go to tool_execution_node
  - More steps remain → continue to next execute_step
  - All done → END
  - Failures occurred → optionally replan

## Key Simplifications

### Removed Complexity

The previous implementation had:
- ❌ Separate planner, executor, replanner nodes with complex logic
- ❌ Review plan node with human-in-the-loop approval
- ❌ Executor with tools as a separate node
- ❌ Complex routing with many conditional edges
- ❌ Separate plan_utils, plan_agent_example files

The new implementation:
- ✅ Single plan-and-execute.py file (~550 lines vs ~1500+ lines)
- ✅ Clearer node responsibilities
- ✅ Simplified routing logic
- ✅ Direct state emission to frontend
- ✅ Easier to understand and maintain

## Frontend Integration

The agent emits state updates using CopilotKit's `copilotkit_emit_state`:

```python
# State structure for frontend
{
    "mode": "plan",  # or "simple"
    "status": "planning" | "executing" | "completed",
    "plan": {
        "objective": "User's goal",
        "summary": "High-level approach",
        "created_at": "ISO timestamp",
        "updated_at": "ISO timestamp"
    },
    "progress": {
        "total_steps": 5,
        "completed": 2,
        "failed": 0,
        "in_progress": 1,
        "pending": 2,
        "current_step_index": 2,
        "percentage": 40
    },
    "steps": [
        {
            "step_number": 1,
            "description": "Step description",
            "expected_outcome": "What should happen",
            "status": "completed" | "in_progress" | "pending" | "failed",
            "result": "Step result (if completed)",
            "error": "Error message (if failed)",
            "is_current": false
        },
        // ... more steps
    ]
}
```

## Frontend Component

The frontend already has `PlanStateRenderer.tsx` that:
- ✅ Listens for plan state updates using `useCoAgentStateRender`
- ✅ Shows progress bar with percentage
- ✅ Displays each step with status icons
- ✅ Highlights current step being executed
- ✅ Shows results and errors inline
- ✅ Real-time updates as steps complete

## Usage

The simplified graph is automatically used in `mcp-hub/app/views.py`:

```python
from app.agent.plan_and_execute import simplified_plan_graph

agent = LangGraphAGUIAgent(
    name="mcpAssistant",
    description="Agent for mcp's",
    graph=simplified_plan_graph
)
```

## Testing

To test the implementation:

1. Start the backend:
   ```bash
   cd mcp-hub
   uv run python manage.py runserver
   # or
   uvicorn assistant.asgi:application --reload
   ```

2. Start the frontend:
   ```bash
   cd mcp-client
   npm run dev
   ```

3. Navigate to `/playground` and ask the agent to perform a complex task:
   - "Search for Python files and analyze them for security issues"
   - "Find all TODO comments in the codebase and create a summary report"
   - "Connect to the weather API and fetch data for 3 cities"

4. You should see:
   - Plan card appear with steps listed
   - Progress bar updating as steps complete
   - Each step showing status (pending → in_progress → completed)
   - Real-time updates as the agent works

## Migration from Old Architecture

If you need to reference the old implementation:
- Old files remain in `app/agent/` (planner.py, executor.py, replanner.py, plan_agent.py)
- They are no longer imported in views.py
- You can remove them once you're confident in the new implementation

## Extending the Implementation

To add features:

1. **Add more sophisticated replanning**:
   - Modify `replan_node` to analyze failures more deeply
   - Add logic to generate alternative approaches

2. **Add plan approval**:
   - Add a review node that uses LangGraph's `interrupt()`
   - Route to review after plan creation

3. **Add step dependencies**:
   - Already supported in PlanStep model
   - Add dependency checking in `execute_step_node`

4. **Add parallel execution**:
   - Identify independent steps
   - Use LangGraph's parallel execution features

## References

- [LangGraph Plan-and-Execute Tutorial](https://langchain-ai.github.io/langgraph/tutorials/plan-and-execute/plan-and-execute/)
- [CopilotKit State Emission](https://docs.copilotkit.ai/shared-state)
- [CopilotKit Generative UI](https://docs.copilotkit.ai/generative-ui)
