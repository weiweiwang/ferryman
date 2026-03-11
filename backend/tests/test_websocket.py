import pytest
import json
from fastapi.testclient import TestClient
from app.main import app

def test_websocket_ping(client):
    """Verify JSON-RPC ping-pong over WebSocket."""
    with client.websocket_connect("/ws") as websocket:
        request = {
            "jsonrpc": "2.0",
            "method": "ping",
            "params": {},
            "id": 1
        }
        websocket.send_text(json.dumps(request))
        data = websocket.receive_text()
        response = json.loads(data)
        assert response["result"] == "pong"
        assert response["id"] == 1

def test_websocket_llm_config_flow(client):
    """Verify getting and setting LLM configs via WebSocket."""
    with client.websocket_connect("/ws") as websocket:
        # 1. Set a config
        set_request = {
            "jsonrpc": "2.0",
            "method": "set_llm_config",
            "params": {
                "provider": "openai",
                "api_key": "sk-test-key",
                "base_url": "https://test.api"
            },
            "id": 2
        }
        websocket.send_text(json.dumps(set_request))
        websocket.receive_text() # Consume success response
        
        # 2. Get configs
        get_request = {
            "jsonrpc": "2.0",
            "method": "get_llm_configs",
            "params": {},
            "id": 3
        }
        websocket.send_text(json.dumps(get_request))
        data = websocket.receive_text()
        response = json.loads(data)
        
        # Verify the result contains our provider
        results = response["result"]
        openai_config = next((c for c in results if c["provider"] == "openai"), None)
        assert openai_config is not None
        assert openai_config["api_key"] == "sk-test-key"
        assert openai_config["base_url"] == "https://test.api"
