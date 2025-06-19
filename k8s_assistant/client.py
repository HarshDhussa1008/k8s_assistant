# mcp_k8s_client.py
import os
import sys
from typing import Any, Dict, List, Tuple
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import asyncio
from contextlib import AsyncExitStack
from k8s_assistant.llms import claude
from k8s_assistant.llms import gpt
from k8s_assistant.llms import deepseek
import logging
import shutil
# logging.basicConfig(level=logging.WARNING, format='%(message)s')

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False

# Set up logging configuration
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler = logging.FileHandler(os.path.join(os.path.dirname(__file__), "mcp_client.log"), mode='a+')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Disable noisy loggers
logging.getLogger('httpx').setLevel(logging.ERROR)
logging.getLogger('anthropic').setLevel(logging.ERROR)
logging.getLogger('openai').setLevel(logging.ERROR)
logging.getLogger('mcp').setLevel(logging.ERROR)
logging.getLogger('anyio').setLevel(logging.ERROR)

exit_in_progress = False

class SuppressOutput:
    def __init__(self):
        self.devnull = open(os.devnull, 'w')
        
    def __enter__(self):
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        sys.stdout = self.devnull
        sys.stderr = self.devnull
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
        self.devnull.close()


def get_separator(char="=", min_width=40):
    """Get a separator line based on terminal width"""
    try:
        # Get terminal width
        terminal_width = shutil.get_terminal_size().columns
        # Use full width, but ensure minimum width
        width = max(terminal_width, min_width)
        return char * width
    except (AttributeError, OSError):
        # Fallback if terminal size can't be determined
        return char * 60  # Default fallback width


class K8sCommandClient:
    
    def __init__(self, server_config: StdioServerParameters):
        """Initialize the K8sCommandClient with server configuration."""
        
        self.server_config = server_config
        self.mcp_client = None  # Placeholder for MCP client
        self.tools = []  # This will be populated later
        self.oci_version = os.getenv("OCI_VERSION", "3.57.0")  # Default version if not set

    async def async_init(self):
        """Asynchronous initialization for MCP Client."""
        
        logger.info("Initializing K8sCommandClient...")
        
        try:
            if os.getenv("ANTHROPIC_API_KEY"):
                self.llm = claude.Claude()
                self.model = "claude-3-5-haiku-20241022"
            else:
                self.llm = deepseek.Deepseek()
                self.model = "deepseek-chat"
            self.summary_llm = gpt.GPT()
            logger.info("LLM clients initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize LLM clients: {e}")
            raise
        
        try:
            # Suppress MCP debug output completely
            with SuppressOutput():
                self.mcp_client = await asyncio.wait_for(
                    self.start_client(self.server_config), 
                    timeout=30
                )
            logger.info("MCP client initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize MCP client: {e}")
            raise
        
        self.system_prompt = self._create_system_prompt()
    
    async def start_client(self, server_params: StdioServerParameters):
        """Start the MCP client and return the session."""
        
        self.exit_stack = AsyncExitStack()
        
        # Setup MCP client and get tools
        async def setup_client(server_params: StdioServerParameters):
            """Setup the MCP client and return the session."""
            
            stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
            logger.info("Stdio transport initialized.")
            self.stdio, self.write = stdio_transport
            logger.info("Stdio transport set up.")
            self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
            logger.info("Client session initialized.")
            await self.session.initialize()
            logger.info("Connected to MCP server.")
            self.mcp_client = self.session
            if self.mcp_client:
                logger.info("MCP client initialized.")
                # List available tools
                response = await self.mcp_client.list_tools()
                for tool in response.tools:
                    # print(f"Tool: {tool.name}, Description: {tool.description}")
                    self.tools.append(
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "input_schema": tool.inputSchema
                        }
                    )
            
                logger.info(f"Available tools: {[tool.name for tool in response.tools]}")
                # print(self.tools)
                return self.mcp_client
        
        try:
            self.mcp_client = await setup_client(server_params)  # Store the result where it should be
            return self.mcp_client
        except Exception as e:
            logger.exception(f"Failed to initialize MCP client: {e}")
            raise
    
    async def cleanup(self):
        """Clean up resources when shutting down."""
        if self.exit_stack:
            try:
                await asyncio.wait_for(self.exit_stack.aclose(), timeout=2.0)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.exception(f"Error during exit stack cleanup: {e}")
            
            finally:
                self.exit_stack = None
                self.stdio = None
                self.write = None
                self.session = None
                self.mcp_client = None
            
        logger.info("Resources cleaned up")
    
    def _create_system_prompt(self) -> str:
        """Create a system prompt that includes information about available tools."""
        
        tool_descriptions = []
        for tool in self.tools:
            # params = "\n".join([f"- {p.name}: {p.description}" for p in tool.inputSchema.keys()])
            tool_descriptions.append(f"Tool: {tool['name']}\nDescription: {tool['description']}\nParameters:\n{tool['input_schema']}\n")
        
        return f"""
    
        # MULTI-CLOUD TROUBLESHOOTING ASSISTANT
        You are an expert cloud operations assistant that automatically determines which tools to use based on the user's request.
        You have access to multiple tools and should intelligently decide which ones to use and in what order.
        
        Available Tools:
        {"\n".join(tool_descriptions)}
        
        ## AUTOMATIC TOOL SELECTION STRATEGY:
        When analyzing a user request, automatically determine the scope and select appropriate tools
    
        # NON-KUBERNETES INTERACTIONS (HIGHEST PRIORITY)
        IMPORTANT OVERRIDE: You are ONLY permitted to use tools for Kubernetes-specific operations.
        For ANY other type of interaction, DO NOT USE ANY TOOLS. Instead:
        
        - For greetings (e.g., "hello", "hi", "good morning"): Respond conversationally
        - For expressions of gratitude (e.g., "thanks", "thank you"): Acknowledge politely
        - For general chit-chat: Engage briefly then guide back to Kubernetes topics
        - For off-topic questions (e.g., weather, news, math): Politely explain you're a Kubernetes assistant and redirect
        - For clarification questions: Answer directly without tools
        
        # KUBERNETES-ONLY Issues:
        You are a Kubernetes expert assistant that helps users interact with their Kubernetes clusters.
        You have access to the following tools that you should use to execute Kubernetes commands, but ONLY when the user is asking
        for Kubernetes-specific operations:
        
        DO NOT perform any write or modifying operations on the Kubernetes cluster.
        STRICTLY AVOID commands like delete, apply, patch, scale, edit, rollout restart, etc.
        
        # OCI-ONLY Issues:
        You are an Oracle Cloud Infrastructure (OCI) expert assistant that helps users interact with the OCI resources. Refer https://docs.oracle.com/en-us/iaas/tools/oci-cli/{self.oci_version}/oci_cli_docs/ for CLI commands.
        
        # MULTI-LAYER Issues (Use BOTH tools automatically)
        You are a multi-layer cloud operations assistant that helps users interact with their Kubernetes clusters and OCI resources. Use the appropriate tools based on the user's request, and execute commands using both Kubernetes and OCI tools as needed.
        
        IMPORTANT: You CANNOT access Kubernetes resources directly. For Kubernetes operations, you MUST use the appropriate tool. 
        When troubleshooting Kubernetes issues, suggest a COMPLETE list of commands that should be run upfront.    
        
        # When NOT to use tools (VERY IMPORTANT):
        - NEVER use tools for greetings or small talk
        - NEVER use tools for expressions of gratitude 
        - NEVER use tools for general questions not related to Kubernetes
        - NEVER use tools for off-topic questions about other subjects
        - NEVER use tools for clarification questions
        - NEVER use tools for confirming completed actions
        
        # Tool usage flow:
        When a user makes a request:
        1. First determine if this is a Kubernetes-specific request or OCI cloud request:
            - If NOT related to Kubernetes: Respond appropriately WITHOUT ANY TOOLS
            - If it's an OCI-specific request: Use the OCI tool to execute commands
            - If it's general conversation: Engage conversationally WITHOUT ANY TOOLS
            - If it's off-topic: Politely redirect to Kubernetes topics WITHOUT ANY TOOLS
            
        2. Only for Kubernetes-specific requests:
            1. Analyze their request to understand what they want to do
            2. Select the appropriate tool to use from the available tools with the server
            3. Format the exact command parameters correctly for the tool
            4. If multiple commands are needed, execute them one by one
            5. After receiving the results, format them in a clear, user-friendly way
            6. Explain what you did and what the results mean
            7. If you need to ask the user for more information, do so clearly
            8. If you encounter an error, provide a helpful error message
            9. Always be polite and professional in your responses
            10. If you are unsure about something, ask the user for clarification
            11. If you need to use a tool, make sure to explain why and how it will help
            12. Always provide context for your actions and decisions
            13. If you need to use multiple tools, explain the sequence of operations
            14. If you need to use a tool, provide the exact command and parameters you will run
            15. If you need to use a tool, explain what the expected output will be
            16. If user gives VMID in the query, use it as the namespace for kubectl commands like ns-<vmid>
            17. If user gives Compartment ID in the query, use it as the compartment-id for OCI commands
            18. If user gives User UUID in the query, use it as the deployment name for kubectl commands like dpy-<user uuid>
        
        Example flow:
        
        1. Non-Kubernetes interaction:
        - User says: "What's the weather like today?"
        - You respond: "I'm specifically designed to help with Kubernetes operations and can't provide weather information. How can I assist you with your Kubernetes cluster today?"
        - NO TOOLS should be used for this interaction.
        
        2. Greeting interaction:
        - User says: "hi" or "hello"
        - You respond: "Hello! I'm your Kubernetes assistant. How can I help you with your Kubernetes cluster today?"
        - NO TOOLS should be used for this interaction.
        
        3. Kubernetes command:
        - User asks: "list all pods in the default namespace"
        - You use the kubectl tool with command="get pods"
        - After receiving results, you explain what pods were found
    
        4. OCI command:
        - User asks: "list all compartments in OCI"
        - You use the OCI tool with command="iam compartment list"
        - After receiving results, you explain what compartments were found
        
        
        ## INTELLIGENT COMMAND SEQUENCING:
        Plan your investigation to build context progressively. Start broad, then narrow --> Follow the data flow --> Use the right tool for the job --> Correlate across tools
        
        Be concise but thorough in your explanations.
        Do NOT suggest theoretical outcomes - only report what was actually returned by the tool execution.
        Dont ask "which tool should I use?" - decide automatically
        
        If you think, you have completed the task , please say "I have completed the task" and provide a summary of what you did.
        If you need to ask the user for more information, do so clearly.
        
        Remember: You're an expert who knows how to investigate complex cloud issues systematically!
        
        """
        
    def _parse_llm_response(self, response: Any, llm_type: str) -> Tuple[List[Dict], List[str]]:
        """Parse LLM response regardless of provider."""
        tool_calls = []
        final_text = []
        
        try:
            if llm_type == "claude":
                # Anthropic Claude format
                for content in response.content:
                    if content.type == 'text':
                        final_text.append(content.text)
                    elif content.type == 'tool_use':
                        tool_calls.append({
                            "id": content.id,
                            "name": content.name,
                            "parameters": content.input
                        })
            
            else:  # OpenAI/DeepSeek format
                if hasattr(response, 'choices') and response.choices:
                    message = response.choices[0].message
                    
                    # Handle text content
                    if hasattr(message, 'content') and message.content:
                        final_text.append(message.content)
                    
                    # Handle tool calls
                    if hasattr(message, 'tool_calls') and message.tool_calls:
                        for tool_call in message.tool_calls:
                            try:
                                parameters = json.loads(tool_call.function.arguments)
                            except (json.JSONDecodeError, AttributeError):
                                parameters = {}
                            
                            tool_calls.append({
                                "id": tool_call.id,
                                "name": tool_call.function.name,
                                "parameters": parameters
                            })
                else:
                    # Fallback: try to extract any text content
                    final_text.append(str(response))
        
        except Exception as e:
            print(f"Error parsing response: {e}")
            # Fallback: convert entire response to string
            final_text.append(f"Response parsing error: {str(response)}")
        
        return tool_calls, final_text
    
    
    async def process_query(self, query: str) -> str:
        """Process a natural language query about Kubernetes operations."""
        
        try:
              
            final_text = []
            command_count = 0
            max_commands = 10  # Safety limit to prevent infinite loops
            
            # Add the current query to the user history
            self.llm.update_llm_history(role="user", content=query)
            self.summary_llm.update_llm_history(role="user", content=query)
            
            while command_count < max_commands:
                
                command_count += 1
                tool_calls = []
                results = []  
                
                # print(f"Processing command {command_count} of {max_commands}")
                
                # Step 1: Ask Claude to interpret the query and decide on tools to use
                response = self.llm.get_response(
                    tools=self.tools,
                    max_tokens=1024,
                    model=self.model,
                    prompt=self._create_system_prompt()
                )
                
                tool_calls, response_text = self._parse_llm_response(response, "claude")
                final_text.extend(response_text)
                
                # for content in response.content:
                #     if content.type == 'text':
                #         final_text.append(content.text)
                #     elif content.type == 'tool_use':
                #         tool_calls.append(
                #             {
                #                 "id": content.id,
                #                 "name": content.name,
                #                 "parameters": content.input
                #             }
                #         )
                        
                if not tool_calls:
                    
                    if len(final_text) == 1:
                        return final_text[0]
                    
                    elif len(final_text) > 1:
                        break
                    
                    else:
                        return "I'm your Kubernetes assistant. For non-Kubernetes queries, I'll respond conversationally. For Kubernetes operations, I'll execute commands to help you. How can I assist with your Kubernetes cluster today?"
                
                    # Claude didn't decide to use any tools, just return its response
                    # if response.stop_reason == 'end_turn' and "I have completed the task" not in response.content[0].text.strip():
                    #     self.llm.update_llm_history(role="user", content="Please continue and run the command you mentioned.")
                    #     continue
                    # else:
                    #     break
                
                
                # Step 2: Execute each tool call and collect results
                for call in tool_calls:
                    # Execute the tool call through MCP client
                    print(f"Executing => {call['name']} {call['parameters']['command']}")
                    result = await self.mcp_client.call_tool(
                        call["name"],
                        call["parameters"]
                    )
                    
                    results.append({
                        "tool": call["name"],
                        "parameters": call["parameters"],
                        "result": result.content[0].text,
                    })
                    
                self.summary_llm.update_llm_history(role="user", content=result.content[0].text)
                
                final_text.append(result.content[0].text)
                # print("Tool call results:", results)
                
                # tool_results_message = []
                # for idx, result in enumerate(results):
                #     tool_results_message.append({
                #         "type": "tool_result",
                #         "tool_use_id": tool_calls[idx]["id"],
                #         "content": result["result"]
                #     })
                # self.llm.update_llm_history(role="user", content=tool_results_message)
                self.llm.add_tool_results_to_history(tool_calls, results)
            
            if command_count >= 1:
                # If we reach here, it means we hit the command limit or completed the task
                
                result_prompt = f"""
                I executed the Kubernetes commands based on your instructions. Based on our conversation history, please explain what does it mean and any next steps the user should take. 
                Please summarize based on the below information, giving more priority to recent findings and correalting it with the past conversation history.
                
                Here is the summary of the recent commands I executed and their outputs. 
                {final_text}
                
                Please format the output in a user-friendly way and summarize the results in this format:

                1. List the commands in a table with command name, namespace, and status.
                2. For each command, display output in a separate code block.
                3. Then give Root Cause Analysis if applicable.
                4. End with clearly marked remediation steps (NOT to be executed) if there are any.
                
                Format all your final output using Markdown with the following structure:
                
                ## Root Cause Analysis (RCA)
                ...

                ## Commands Executed
                
                | # | Command | Namespace | Outcome |

                ## 📄 Command Output Summary
                ...

                ## Observations
                ...

                ## Suggested Remediation (Execute carefully)
                
                """
                
                # Step 3: Summarize the results and provide next steps
                final_response = self.summary_llm.get_response(
                    max_tokens=2048,  # Increase max_tokens to handle larger responses
                    # model="claude-3-7-sonnet-20250219",
                    model="gpt-4.1-nano-2025-04-14",
                    prompt=result_prompt   
                )
                # print("Final response:", final_response)
                
                return_response = "Analysis Limit Exceeded!\n" if command_count >= max_commands else ""
                return_response += f"Here is the summary of actions I have performed.\n\n"
                return (return_response + final_response.choices[0].message.content) if (len(final_response.choices) > 0 and final_response.choices[0].message and final_response.choices[0].message.content) else (return_response + "\n".join(final_text))

            
            if final_text and len(final_text) > 0:
                return f"Here is the summary of actions I have performed.\n {final_text}"
            else:
                return "I'm your Kubernetes assistant. How can I help you with your Kubernetes cluster today?"
            
        except Exception as e:
            
            logger.exception("An error occurred while processing the query")
            import traceback
            logger.error(traceback.format_exc())
            return "An unexpected error occurred while processing your request. Please try again later."

async def force_exit(client: K8sCommandClient):
    """Force exit the application"""
    global exit_in_progress
    
    if exit_in_progress:
        return
    exit_in_progress = True
    
    if client:
        try:
            # Give cleanup 1 second max, then force exit
            await asyncio.wait_for(client.cleanup(), timeout=1.0)
        except:
            pass  # Ignore any cleanup errors
    
    # Force exit
    os._exit(0)


async def async_main():
    
    try:
        # Create server parameters for stdio connection
        server_path = os.path.join(os.path.dirname(__file__), "server.py")
        server_params = StdioServerParameters(
            command="python3.12",  # Executable
            args=[server_path],  # Optional command line arguments
            env=None,  # Optional environment variables
        )
        
        client = K8sCommandClient(server_params)
        await client.async_init()  # Perform asynchronous initialization
        # print(f"Server parameters: {server_params}\n")
        
        while True:
            try:
                query = input("How can I help you today ?\n")
                if not query or query.lower() == "exit" or query.lower() == "quit" or query.lower() == "q" or "bye" in query.lower() or "thank" in query.lower():
                    print("Exiting...")
                    break
                
                # Check if the query is empty
                if not query.strip():
                    print("Sorry I could not understand!\n\n")
                    continue
                # print(f"Query: {query}")
                
                result = await client.process_query(query)  # Ensure process_query is awaited
                # print("Result from processing query:")
                
                separator = get_separator()
                print(f"\n{separator}\n\n")
                print(result)
                print(f"\n\n{separator}\n")
            
            except KeyboardInterrupt:
                print("\nExiting...")
                await force_exit(client)
                break
            except EOFError:
                print("\nExiting...")
                await force_exit(client)
                break
            except Exception as e:
                print(f"An error occurred: {e}")
                logger.exception("An error occurred while processing the query")
                import traceback
                logger.error(traceback.format_exc())
            
        await client.cleanup()  # Ensure cleanup is awaited
        logger.info("Client cleanup completed.")
    
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        await force_exit(client)


if __name__ == "__main__":
    asyncio.run(async_main())
