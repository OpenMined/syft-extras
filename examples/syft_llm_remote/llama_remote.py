from __future__ import annotations

import httpx
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from loguru import logger
from pydantic import BaseModel, Field, validator
from syft_event.types import Request

from syft_rpc_client import SyftRPCClient


# ----------------- Request/Response Models -----------------

class OllamaRequest(BaseModel):
    """Request to send to a remote Ollama instance."""
    model: str = Field(description="Name of the Ollama model to use")
    prompt: str = Field(description="The prompt text to send to the model")
    system: Optional[str] = Field(default=None, description="Optional system prompt")
    temperature: float = Field(default=0.7, description="Sampling temperature")
    max_tokens: Optional[int] = Field(default=None, description="Maximum tokens to generate")
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), 
                         description="Timestamp of the request")
    options: Optional[Dict[str, Any]] = Field(default=None, description="Additional Ollama options")


class OllamaResponse(BaseModel):
    """Response from a remote Ollama instance."""
    model: str = Field(description="Model that generated the response")
    response: str = Field(description="Generated text response")
    error: Optional[str] = Field(default=None, description="Error message, if any")
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), 
                         description="Timestamp of the response")
    total_duration_ms: Optional[int] = Field(default=None, description="Processing time in milliseconds")
    
    @validator('error')
    def check_error(cls, v, values):
        if v and not values.get('response'):
            values['response'] = f"Error: {v}"
        return v


# ----------------- Ollama Client Implementation -----------------

class OllamaClient(SyftRPCClient):
    """Client for sending prompts to remote Ollama instances."""
    
    def __init__(self, 
                 config_path: Optional[str] = None, 
                 ollama_url: str = "http://localhost:11434"):
        """Initialize the Ollama client.
        
        Args:
            config_path: Optional path to a custom config.json file
            ollama_url: URL of the local Ollama instance, if applicable
        """
        super().__init__(
            config_path=config_path,
            app_name="ollama_remote",
            endpoint="/generate",
            request_model=OllamaRequest,
            response_model=OllamaResponse
        )
        self.ollama_url = ollama_url
        
    def _handle_request(self, request: OllamaRequest, ctx: Request, box) -> OllamaResponse:
        """Process an incoming Ollama request by forwarding to the local Ollama instance."""
        logger.info(f"🔔 RECEIVED: Ollama request for model '{request.model}'")
        
        try:
            # Prepare the request payload for Ollama
            payload = {
                "model": request.model,
                "prompt": request.prompt,
                "stream": False,  # Ensure we're not getting a streaming response
            }
            
            # Add optional parameters
            if request.system:
                payload["system"] = request.system
            if request.temperature is not None:
                payload["temperature"] = request.temperature
            if request.max_tokens is not None:
                payload["max_tokens"] = request.max_tokens
            if request.options:
                payload.update(request.options)
                
            # Send request to the local Ollama instance
            response = httpx.post(
                f"{self.ollama_url}/api/generate", 
                json=payload,
                timeout=120.0  # Longer timeout for LLM generation
            )
            
            if response.status_code == 200:
                # Improved JSON parsing to handle different response formats
                try:
                    # Try to parse as normal JSON first
                    data = response.json()
                except json.JSONDecodeError as e:
                    # If that fails, try to extract the first valid JSON object
                    try:
                        text = response.text
                        # Find the first complete JSON object
                        json_start = text.find('{')
                        json_end = text.rfind('}') + 1
                        if json_start >= 0 and json_end > json_start:
                            data = json.loads(text[json_start:json_end])
                        else:
                            raise ValueError(f"Could not find valid JSON in response: {text[:100]}...")
                    except Exception as nested_e:
                        return OllamaResponse(
                            model=request.model,
                            response="",
                            error=f"JSON parsing error: {str(e)}. Nested error: {str(nested_e)}",
                            ts=datetime.now(timezone.utc)
                        )
                
                # Extract and return the response
                return OllamaResponse(
                    model=request.model,
                    response=data.get("response", ""),
                    total_duration_ms=data.get("total_duration", 0),
                    ts=datetime.now(timezone.utc)
                )
            else:
                return OllamaResponse(
                    model=request.model,
                    response="",
                    error=f"HTTP Error {response.status_code}: {response.text}",
                    ts=datetime.now(timezone.utc)
                )
        except Exception as e:
            logger.error(f"Error processing Ollama request: {e}")
            return OllamaResponse(
                model=request.model,
                response="",
                error=str(e),
                ts=datetime.now(timezone.utc)
            )
    
    def generate(self, 
                 to_email: str, 
                 model: str, 
                 prompt: str, 
                 system: Optional[str] = None,
                 temperature: float = 0.7,
                 max_tokens: Optional[int] = None) -> Optional[OllamaResponse]:
        """Send a generation request to a remote Ollama instance.
        
        Args:
            to_email: Email of the datasite hosting the Ollama instance
            model: Name of the LLM model to use
            prompt: The prompt text to send
            system: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            
        Returns:
            OllamaResponse with the generated text if successful, None otherwise
        """
        request = OllamaRequest(
            model=model,
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            ts=datetime.now(timezone.utc)
        )
        
        return self.send_request(to_email, request)
    
    def list_available_models(self) -> List[Dict[str, Any]]:
        """List all models available on the local Ollama instance.
        
        Returns:
            List of model information dictionaries
        """
        try:
            response = httpx.get(f"{self.ollama_url}/api/tags")
            if response.status_code == 200:
                return response.json().get("models", [])
            else:
                logger.error(f"Failed to get models: HTTP {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return []


# ----------------- API Functions -----------------

def client(config_path: Optional[str] = None, 
           ollama_url: str = "http://localhost:11434") -> OllamaClient:
    """Create and return a new Ollama client.
    
    Args:
        config_path: Optional path to a custom config.json file
        ollama_url: URL of the local Ollama instance
        
    Returns:
        An OllamaClient instance
    """
    return OllamaClient(config_path, ollama_url)
