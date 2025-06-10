import os
from typing import Dict, List
import anthropic
from k8s_assistant.llms.LLM import LLM

class Claude(LLM):
    """Claude class for interacting with the Anthropic Claude model."""
    
    def __init__(self):
        
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        self.anthropic_client = self._initialize_client()
        self.user_history = []


    def _initialize_client(self) -> anthropic.Anthropic:
        """Initialize and return the Anthropic client."""
        
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        return anthropic.Anthropic(api_key=self.api_key)

    
    def get_response(self, max_tokens: int, model: str, prompt: str, tools: list=[]) -> dict:
        """Get a response from the Claude model."""
        
        # Call the Claude API to get a response
        response = self.anthropic_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=prompt,
            messages=self.user_history,
            tools=tools
        )
        
        # Append the user history to the Claude model
        self.update_llm_history(
            role="assistant",
            content=response.content
        )
        
        return response

    def format_tool_results(self, tool_calls: List[Dict], results: List[Dict]) -> List[Dict]:
        """Format tool results for Anthropic Claude."""
        tool_results_message = []
        for idx, result in enumerate(results):
            tool_results_message.append({
                "type": "tool_result",
                "tool_use_id": tool_calls[idx]["id"],
                "content": result["result"]
            })
        return tool_results_message
    
    def update_llm_history(self, role: str, content: str|list) -> None:
        """Update the user history with the latest user input."""
        
        self.user_history.append(
            {
                "role": role,
                "content": content
            }
        )
        