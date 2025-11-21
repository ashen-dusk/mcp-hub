# Adding Reasoning/Thinking to Your AI Agent

This guide shows you how to add visible reasoning text to your LangGraph agent, similar to what you see in ChatGPT and Cursor.

## 🎯 Two Approaches

### **Approach 1: Claude Extended Thinking (Recommended)**
✅ Native support from Anthropic Claude models
✅ Automatic reasoning generation
✅ Streamed in real-time
✅ Best quality reasoning

### **Approach 2: Custom Reasoning Node**
✅ Works with ANY LLM (OpenAI, DeepSeek, etc.)
✅ Explicit chain-of-thought prompting
✅ Full control over reasoning format
✅ Can be customized per use case

---

## 📦 Installation

First, install the required dependency:

```bash
# Install dependencies
uv pip install -e .

# Or manually install langchain-anthropic
uv pip install langchain-anthropic
```

Set up your environment variables:

```bash
# .env file
ANTHROPIC_API_KEY=your_api_key_here
```

---

## 🔧 Approach 1: Using Claude Extended Thinking

### How It Works

When you enable `extended_thinking` on Claude models, they automatically generate reasoning before responding. The thinking is returned as a separate content block in the response.

### Setup (Already Done! ✅)

The code has been updated in:
- `app/agent/model.py` - Claude support with extended thinking
- `app/agent/chat.py` - Thinking block extraction

### Using Claude with Extended Thinking

Simply specify a Claude model when creating your agent:

```python
# In your frontend or API request
{
  "model": "claude-sonnet-4-5",  # or "claude-opus-4"
  "messages": [...],
  "config": {
    "temperature": 0.7
  }
}
```

### What Happens

1. Claude model receives the prompt
2. **Thinking phase**: Model generates internal reasoning
3. **Response phase**: Model generates the actual answer
4. Both are returned and can be displayed separately

### Streaming Thinking Blocks

The thinking blocks are automatically captured and stored in `response.additional_kwargs['thinking_blocks']`. The AG-UI protocol will stream these separately from the main content.

Example thinking block:
```json
{
  "type": "thinking",
  "content": "Let me break this down step by step:\n1. First, I need to understand what the user is asking...\n2. Then I should consider the available tools...\n3. The best approach would be..."
}
```

---

## 🔧 Approach 2: Custom Reasoning Node (For OpenAI, DeepSeek, etc.)

### How It Works

For models without native extended thinking, we create a two-step process:
1. **Reasoning Node**: Asks the model to think step-by-step
2. **Chat Node**: Generates the final answer using the reasoning

### Setup

#### Option A: Modify Existing Graph

Edit `app/agent/agent.py`:

```python
from app.agent.reasoning import reasoning_node, reasoning_chat_node

# Replace the chat_node with reasoning_chat_node
graph_builder.add_node("chat", reasoning_chat_node)
```

#### Option B: Create a New Graph with Reasoning

Create `app/agent/reasoning_graph.py`:

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.agent.types import AgentState
from app.agent.reasoning import reasoning_node, reasoning_chat_node
from app.agent.agent import async_tool_node, should_continue

# Create graph
graph_builder = StateGraph(AgentState)

# Add nodes
graph_builder.add_node("reasoning", reasoning_node)
graph_builder.add_node("chat", reasoning_chat_node)
graph_builder.add_node("tools", async_tool_node)

# Add edges
graph_builder.add_edge(START, "reasoning")
graph_builder.add_edge("reasoning", "chat")
graph_builder.add_conditional_edges(
    "chat",
    should_continue,
    {
        "tools": "tools",
        "end": END
    }
)
graph_builder.add_edge("tools", "chat")

# Compile
checkpointer = MemorySaver()
reasoning_graph = graph_builder.compile(checkpointer=checkpointer)
```

#### Option C: Toggle Reasoning On/Off

Create a conditional graph that uses reasoning only when requested:

```python
from app.agent.types import AgentState

def should_use_reasoning(state: AgentState) -> str:
    """Decide whether to use reasoning based on config"""
    assistant_config = state.get("assistant", {}).get("config", {})
    use_reasoning = assistant_config.get("enable_reasoning", False)

    if use_reasoning:
        return "reasoning"
    else:
        return "chat"

# In your graph
graph_builder.add_conditional_edges(
    START,
    should_use_reasoning,
    {
        "reasoning": "reasoning_node",
        "chat": "chat_node"
    }
)
```

---

## 🎨 Frontend Display

### AG-UI Protocol Events

When reasoning is generated, it's included in the streamed events. You can handle it in your frontend:

```javascript
// Example: Handling AG-UI events
const eventSource = new EventSource('/langgraph-agent');

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);

  // Check for thinking/reasoning content
  if (data.type === 'thinking') {
    // Display reasoning in a special UI component
    displayThinking(data.content);
  } else if (data.type === 'message') {
    // Display regular message
    displayMessage(data.content);
  }
};
```

### UI Suggestions

**ChatGPT-style Reasoning Display:**
```
┌─────────────────────────────────────┐
│ 💭 Thinking...                      │
│                                     │
│ Let me analyze this step by step:  │
│ 1. First, I need to...             │
│ 2. Then, I should...               │
│ 3. Finally, I can...               │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│ Based on my analysis, here's the   │
│ answer to your question...         │
└─────────────────────────────────────┘
```

**Cursor-style Reasoning Display:**
```
[Reasoning] Analyzing the codebase...
[Reasoning] Found 3 relevant files...
[Reasoning] Best approach is to...

[Response] I'll help you with that...
```

---

## 🧪 Testing

### Test with Claude Extended Thinking

```bash
# Make a request with Claude model
curl -X POST http://localhost:8000/langgraph-agent \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [
      {
        "role": "user",
        "content": "Explain how to implement a binary search tree"
      }
    ],
    "assistant": {
      "config": {
        "temperature": 0.7
      }
    }
  }'
```

### Test with Custom Reasoning (OpenAI/DeepSeek)

```bash
curl -X POST http://localhost:8000/langgraph-agent \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {
        "role": "user",
        "content": "Explain how to implement a binary search tree"
      }
    ],
    "assistant": {
      "config": {
        "temperature": 0.7,
        "enable_reasoning": true
      }
    }
  }'
```

---

## 📝 Customizing Reasoning

### Adjust Reasoning Prompt

Edit `app/agent/reasoning.py`:

```python
reasoning_prompt = f"""Before answering, analyze this carefully:

Question: {last_user_message.content}

Think through:
1. What is the user really asking?
2. What information do I need?
3. What's the best approach?
4. Are there any edge cases?

Your step-by-step reasoning:"""
```

### Add Domain-Specific Reasoning

```python
async def code_reasoning_node(state: AgentState, config: RunnableConfig):
    """Reasoning node specialized for code-related tasks"""
    reasoning_prompt = f"""
Let's analyze this code-related question systematically:

Question: {last_user_message.content}

Consider:
1. What programming patterns are involved?
2. What are the potential bugs or issues?
3. What are the best practices to follow?
4. How can we ensure correctness?

Your technical reasoning:"""

    # ... rest of the implementation
```

---

## 🚀 Best Practices

### 1. **Choose the Right Approach**
- Use Claude Extended Thinking for best results
- Use Custom Reasoning for non-Claude models
- Consider cost vs. quality trade-offs

### 2. **Control Reasoning Length**
- Set `max_tokens` appropriately
- Extended thinking can be verbose
- Balance detail vs. speed

### 3. **Cache Reasoning**
- Cache reasoning for repeated questions
- Store in Redis for session continuity

### 4. **Monitor Performance**
- Track reasoning generation time
- Measure impact on response latency
- A/B test with and without reasoning

### 5. **User Experience**
- Make reasoning collapsible in UI
- Add loading indicators
- Allow users to skip reasoning

---

## 🔍 Debugging

### Check if Thinking is Captured

```python
# Add logging in chat.py
if thinking_blocks:
    print(f"💭 Thinking blocks: {thinking_blocks}")
else:
    print("⚠️ No thinking blocks captured")
```

### Verify Model Configuration

```python
# In model.py
print(f"Model config: {model_kwargs}")
print(f"Extended thinking enabled: {model_kwargs.get('extended_thinking')}")
```

### Test Reasoning Extraction

```python
# Test the reasoning node directly
from app.agent.reasoning import reasoning_node
result = await reasoning_node(test_state, test_config)
print(f"Reasoning: {result.get('reasoning')}")
```

---

## 📚 Additional Resources

- [Claude Extended Thinking Docs](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [AG-UI Protocol Spec](https://github.com/anthropics/ag-ui-protocol)

---

## 🎯 Quick Start Summary

**For Claude users:**
1. ✅ Dependencies installed (already done)
2. ✅ Model configuration updated (already done)
3. ✅ Chat node extracts thinking (already done)
4. Set `model: "claude-sonnet-4-5"` in your requests
5. Update frontend to display thinking blocks

**For other LLM users:**
1. Import reasoning nodes
2. Modify your graph to use `reasoning_chat_node`
3. Set `enable_reasoning: true` in config
4. Update frontend to display reasoning

That's it! Your agent now has reasoning capabilities! 🎉
