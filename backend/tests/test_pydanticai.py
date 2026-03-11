import pytest
import asyncio
import os
import logging
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

logger = logging.getLogger(__name__)

@pytest.mark.asyncio
async def test_gemini_integration():
    """
    Integration test for PydanticAI + Gemini.
    Requires a valid GOOGLE_API_KEY in Ferryman settings or ENV.
    """
    # Hardcoded test values as requested to bypass DB state issues during tests
    api_key = "***REMOVED_GEMINI_API_KEY***"
    base_url = "https://generativelanguage.googleapis.com"
    
    if not api_key:
        api_key = os.getenv("GOOGLE_API_KEY")
    assert api_key, "GOOGLE_API_KEY not found in environment"

    logger.info(f"📡 Testing Gemini with API Key: {api_key[:8]}...")
    
    # Initialize Provider & Model matching the pattern in kernel.py
    provider = GoogleProvider(api_key=api_key, base_url=base_url)
    model_name = 'gemini-3-flash-preview' # Or use config.get_active_model_id()
    
    model = GoogleModel(model_name, provider=provider)
    agent = Agent(model=model)
    
    try:
        result = await agent.run('Respond with the word "SUCCESS"')
        assert "SUCCESS" in result.output.upper()
        
        # Verify Token Usage statistics
        usage = result.usage()
        logger.info(f"✅ Gemini Integration Test Passed: {result.output}")
        logger.info(f"📊 Token Usage: {usage.input_tokens} Input | {usage.output_tokens} Output | {usage.total_tokens} Total")
        
        assert usage.total_tokens > 0
    except Exception as e:
        pytest.fail(f"Gemini Integration Test Failed: {e}")

if __name__ == "__main__":
    # Allow running this test directly
    asyncio.run(test_gemini_integration())
