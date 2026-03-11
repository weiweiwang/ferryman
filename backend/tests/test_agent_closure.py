import pytest
import logging
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import ModelResponse, ToolCallPart, TextPart
from app.core.kernel import FerrymanKernel
from app.models.schemas import TaskStatus

logger = logging.getLogger(__name__)

@pytest.mark.asyncio
async def test_agent_execution_closure(monkeypatch):
    """
    Verifies the full 'Closure' of a MasterAgent instruction using FunctionModel to simulate turns.
    1. Instruction received.
    2. Agent decides to call a tool (simulated).
    3. Tool execution completes (tracked by kernel).
    4. Agent provides final response.
    """
    # 1. Setup Kernel with Mock Model
    kernel = FerrymanKernel()
    
    # Mock model classes to prevent API key validation during init
    from pydantic_ai.models.gemini import GeminiModel
    from pydantic_ai.models.openai import OpenAIModel
    from pydantic_ai.models.anthropic import AnthropicModel
    monkeypatch.setattr("pydantic_ai.models.gemini.GeminiModel.__init__", lambda *args, **kwargs: None)
    monkeypatch.setattr("pydantic_ai.models.openai.OpenAIModel.__init__", lambda *args, **kwargs: None)
    monkeypatch.setattr("pydantic_ai.models.anthropic.AnthropicModel.__init__", lambda *args, **kwargs: None)
    
    # helper to check role
    def get_role(m):
        if hasattr(m, 'role'): return m.role
        if hasattr(m, 'parts'):
            # TextPart or ToolCallPart? 
            # In pydantic-ai, user/assistant/tool messages have specific roles.
            pass
        return None

    # 1. Define a Mock Model Function that simulates 2 turns
    async def mock_agent_logic(messages, info):
        # In pydantic-ai, tool results come back in a ModelResult or similar.
        # Let's count turns. Turn 0 is User message.
        if len(messages) <= 1:
            # Turn 1: Call 'list_files' tool
            # ToolCallPart needs: tool_name, args, tool_call_id
            return ModelResponse(parts=[
                ToolCallPart(tool_name="list_files", args={"directory": "."}, tool_call_id="call_001")
            ])
        else:
            # Turn 2: Final response after tool result
            return ModelResponse(parts=[
                TextPart(content="I see the following files: mock_file.txt. Execution completed successfully. OK.")
            ])

    mock_model = FunctionModel(mock_agent_logic)
    
    # 2. Inject mock model into kernel's agent creation
    original_build_agent = kernel._build_agent
    def mock_build_agent(session_id, system_prompt):
        agent = original_build_agent(session_id, system_prompt)
        agent.model = mock_model
        return agent
        
    monkeypatch.setattr(kernel, "_build_agent", mock_build_agent)

    # 3. Execute
    result = await kernel.run_master_agent("Help me list files", session_id="test_session")
    if result["status"] == "error":
        logger.debug(f"DEBUG: Agent Error: {result['message']}")
    
    # 4. Verify Closure
    assert result["status"] == "success", f"Agent failed: {result.get('message')}"
    assert "successfully" in result["response"]
    assert "OK" in result["response"]
    
    # 5. Verify task tracking
    task_id = result["task_id"]
    from app.core.db import get_session
    with get_session() as session:
        from app.models.database import Task
        task = session.get(Task, task_id)
        assert task.status == TaskStatus.SUCCESS
        assert "response_preview" in task.metadata_
