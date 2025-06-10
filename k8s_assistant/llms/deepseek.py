import json
import os
from typing import Dict, List
from openai import OpenAI
from k8s_assistant.llms.LLM import LLM
from k8s_assistant.llms import gpt  # Import GPT class for summarization
import tiktoken

class Deepseek(LLM):
    """GPT class for interacting with the OpenAI GPT model."""
    
    def __init__(self):
        
        model_id = "deepseek.r1-v1:0"
        self.user_history = []
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.depseek_client = self._initialize_client()
        
        self.max_context_tokens = 60000  # Leave buffer for response
        self.max_response_tokens = 4000  # Reasonable response size
        self.summarization_threshold = 0.8  # Trigger summarization at 80% capacity
        self.summary_llm =  gpt.GPT()
        
        try:
            self.tokenizer = tiktoken.encoding_for_model("gpt-4")
        except:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        
        
    def _initialize_client(self) -> OpenAI:
        """Initialize and return the Anthropic client."""
        
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable not set")
        return OpenAI(api_key=self.api_key, base_url="https://api.deepseek.com/v1")
    
    def _count_tokens(self, text: str) -> int:
        """Count tokens in a text string."""
        return len(self.tokenizer.encode(text))
    
    def _count_message_tokens(self, messages: List[Dict]) -> int:
        """Count total tokens in a list of messages."""
        total_tokens = 0
        for message in messages:
            content = message.get("content", "")
            if content:
                total_tokens += self._count_tokens(str(content))
            
            # Count tool call tokens if present
            if "tool_calls" in message:
                for tool_call in message["tool_calls"]:
                    total_tokens += self._count_tokens(json.dumps(tool_call))
        
        return total_tokens
    
    def _summarize_conversation(self, messages: List[Dict]) -> str:
        """Summarize old conversation history to reduce token count."""
        if len(messages) <= 2:
            return ""
        
        # Keep the first message (system prompt) and last few messages
        messages_to_summarize = messages[1:-3] if len(messages) > 6 else messages[1:-1]
        
        if not messages_to_summarize:
            return ""
        
        # Create a summary prompt
        conversation_text = ""
        for msg in messages_to_summarize:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if content:
                conversation_text += f"{role}: {content}\n"
        
        summary_prompt = f"""Please provide a concise summary of this conversation history:

{conversation_text}

Summary:"""
        
        try:
            response = self.summary_llm.get_response(
                max_tokens=500,  # Increase max_tokens to handle larger responses
                model="gpt-4.1-nano-2025-04-14",
                prompt=summary_prompt
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Warning: Could not generate summary: {e}")
            return "Previous conversation history (details omitted due to length)"
    
    def _manage_context_length(self, new_prompt: str, tools: list = []) -> None:
        """Manage conversation history to stay within context limits."""
        # Calculate current token count
        current_tokens = self._count_message_tokens(self.user_history)
        new_prompt_tokens = self._count_tokens(new_prompt)
        tools_tokens = self._count_tokens(json.dumps(tools)) if tools else 0
        
        total_tokens = current_tokens + new_prompt_tokens + tools_tokens
        
        # print(f"Current tokens: {current_tokens}, New prompt: {new_prompt_tokens}, Tools: {tools_tokens}")
        # print(f"Total tokens: {total_tokens}, Max allowed: {self.max_context_tokens}")
        
        # If we're approaching the limit, summarize old history
        if total_tokens > (self.max_context_tokens * self.summarization_threshold):
            print("Context getting large, summarizing old conversation...")
            
            if len(self.user_history) > 4:
                # Summarize middle portion of conversation
                summary = self._summarize_conversation(self.user_history)
                
                # Keep first message, add summary, keep last 2 messages
                new_history = []
                if self.user_history:
                    new_history.append(self.user_history[0])  # Keep first message
                
                if summary:
                    new_history.append({
                        "role": "system", 
                        "content": f"Previous conversation summary: {summary}"
                    })
                
                # Keep last 2 messages
                if len(self.user_history) >= 2:
                    new_history.extend(self.user_history[-2:])
                
                self.user_history = new_history
                # print(f"Conversation summarized. New history length: {len(self.user_history)}")
        
        # Final check - if still too long, trim more aggressively
        current_tokens = self._count_message_tokens(self.user_history)
        if current_tokens + new_prompt_tokens + tools_tokens > self.max_context_tokens:
            # print("Still too long, trimming more aggressively...")
            # Keep only the last 2 messages
            self.user_history = self.user_history[-2:] if len(self.user_history) >= 2 else self.user_history
    
    def _convert_tools_to_openai_format(self, tools: list) -> list:
        """Convert MCP tools format to OpenAI/DeepSeek compatible format."""
        if not tools:
            return []
        
        converted_tools = []
        for tool in tools:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {})
                }
            }
            converted_tools.append(openai_tool)
        
        return converted_tools

    def get_response(self, max_tokens: int, model: str, prompt: str, tools: list=[]) -> dict:
        """Get a response from the GPT model."""
        
        # print(f"Prompt: {prompt}")
        # print(f"Model: {model}")
        # print(f"Max Tokens: {max_tokens}")
        # print(f"Tools: {tools}")
        # print(f"User History: {self.user_history}")
        
        max_tokens = min(max_tokens, self.max_response_tokens)
        self._manage_context_length(prompt, tools)
        
        # Call the Deepseek Model to get a response
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                *self.user_history,
                {"role": "user", "content": prompt}
            ]
        }
        
        if tools:
            converted_tools = self._convert_tools_to_openai_format(tools)
            kwargs["tools"] = converted_tools
            
        try:
            response = self.depseek_client.chat.completions.create(**kwargs)
        except Exception as e:
            if "maximum context length" in str(e):
                print("Context still too long, making emergency trim...")
                self.user_history = []
                kwargs["messages"] = [{"role": "user", "content": prompt}]
                response = self.depseek_client.chat.completions.create(**kwargs)
            else:
                raise e
        
        # Append the user history to the GPT model
        self.update_llm_history(
            role="assistant",
            content=response.choices[0].message.content if len(response.choices) > 0 else ""
        )
        
        return response
    
    def format_tool_results(self, tool_calls: List[Dict], results: List[Dict]) -> List[Dict]:
        """Format tool results for DeepSeek (same as OpenAI format)."""
        # DeepSeek follows OpenAI format
        tool_messages = []
        for idx, result in enumerate(results):
            tool_messages.append({
                "role": "tool", 
                "tool_call_id": tool_calls[idx]["id"],
                "content": str(result["result"])
            })
        return tool_messages
    
    def add_tool_results_to_history(self, tool_calls: List[Dict], results: List[Dict]) -> None:
        """Override for DeepSeek's tool result handling."""
        # First add assistant message with tool calls (like OpenAI)
        assistant_message = {
            "role": "assistant", 
            "content": None,
            "tool_calls": []
        }
        
        for call in tool_calls:
            assistant_message["tool_calls"].append({
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call["parameters"])
                }
            })
        
        self.user_history.append(assistant_message)
        
        # Then add tool results
        tool_messages = self.format_tool_results(tool_calls, results)
        for tool_message in tool_messages:
            self.user_history.append(tool_message)
    
    
    def update_llm_history(self, role: str, content: str|list) -> None:
        """Update the user history with the latest user input."""
        
        if isinstance(content, list) and role == "assistant":
            # Try to extract text content from choices if it's a list
            try:
                formatted_content = content[0].message.content if len(content) > 0 else ""
            except (AttributeError, IndexError):
                formatted_content = str(content)
        else:
            formatted_content = content
        
        self.user_history.append(
            {
                "role": role,
                "content": formatted_content
            }
        )
    
    def clear_history(self) -> None:
        """Clear conversation history."""
        self.user_history = []
        
    def get_history_summary(self) -> Dict:
        """Get summary of current conversation state."""
        return {
            "message_count": len(self.user_history),
            "estimated_tokens": self._count_message_tokens(self.user_history),
            "max_context_tokens": self.max_context_tokens
        }