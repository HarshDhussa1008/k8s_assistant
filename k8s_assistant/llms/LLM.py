from typing import Any, Dict, List
from abc import ABC, abstractmethod
    

class LLM(ABC):
    
    @abstractmethod
    def _initialize_client(self) -> Any:
        """Initialize and return the LLM client."""
        pass
    
    @abstractmethod
    def get_response(self, max_tokens: int, model: str, prompt: str, tools: list=[]) -> dict:
        """Get a response from the LLM model."""
        pass
    
    @abstractmethod
    def update_llm_history(self, role: str, content: str|list) -> None:
        """Update the user history with the latest user input."""
        pass
    
    def get_api_key(self) -> str:
        """Get the API key for the LLM."""
        return self.api_key
    
    @abstractmethod
    def format_tool_results(self, tool_calls: List[Dict], results: List[Dict]) -> List[Dict]:
        """Format tool results for the LLM."""
        pass
    
    def add_tool_results_to_history(self, tool_calls: List[Dict], results: List[Dict]) -> None:
        """Add tool results to conversation history in provider-specific format."""
        formatted_results = self.format_tool_results(tool_calls, results)
        self.update_llm_history(role="user", content=formatted_results)