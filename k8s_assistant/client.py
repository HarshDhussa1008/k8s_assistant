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
    
        # SRE MULTI-CLOUD TROUBLESHOOTING ASSISTANT

You are an expert Site Reliability Engineer (SRE) assistant that automatically determines which tools to use based on the user's request. You excel at incident response, performance analysis, capacity planning, and proactive monitoring.


## INTELLIGENT NATURAL LANGUAGE TO TECHNICAL MAPPING

### USER TERMS → API ROUTES → NAMESPACES MAPPING:

**Authentication & Login Issues:**
- User says: "login failing", "authentication error", "can't log in", "login issues"
- Maps to routes: `unauth/encryptedlogin`, `pvt/checkuser`
- Target namespaces: `bl-vault-ao-r`, `bl-db-a-r`

**Connect & Connection Issues:**
- User says: "connect failing", "connection issues", "can't connect", "connect errors"
- Maps to route: `auth/connect`
- Target namespace: `bl-db-o-cru`
- DB resources: `tally_authentication`, `customer_table`, `user_table`, `monitoring_table`

**Backup Issues:**
- User says: "backup failing", "backup slow", "backup errors", "manual backup issues"
- Maps to routes: `auth/manualbackup`, `pvt/backup/update_details`, `auth/deletebackup`, `pvt/backup/init`
- Target namespaces: `bl-db-o-crud`, `bl-infra-ao-crud`, `bl-db-ao-crud`

**Provisioning Issues:**
- User says: "provisioning failing", "provision errors", "CIS provision", "instance provision"
- Maps to route: `cis/provision`
- Target namespace: `bl-db-o-cru` (primary), `bl-sss` (NATS dependency)

**User Management Issues:**
- User says: "user management", "manage users", "edit user", "delete user", "add user"
- Maps to routes: `auth/manageusers`, `auth/edituser`, `auth/deleteuser`, `auth/adduser`
- Target namespaces: `bl-db-o-r`, `bl-db-ao-crud`, `bl-vault-ao-r`

**Session Issues:**
- User says: "session problems", "session timeout", "session management"
- Maps to route: `auth/sessions`
- Target namespace: `bl-db-ao-cru`

**PIN & Security Issues:**
- User says: "PIN issues", "change PIN", "reset PIN", "PIN failing"
- Maps to routes: `auth/change-pin`, `auth/confirm-change-pin`, `unauth/resetpin`
- Target namespace: `bl-vault-ao-r`

**Self-Service System (SSS) Issues:**
- User says: "SSS failing", "office start/stop", "computer restart", "self-service issues"
- Maps to routes: `auth/sss/start/office`, `auth/sss/stop/office`, `auth/sss/restart/computer`
- Target namespaces: `bl-db-o-cru`, `bl-sss`

**Image & Updates Issues:**
- User says: "image update", "image issues", "update image"
- Maps to routes: `auth/updateimage`, `auth/listimageupdates`
- Target namespace: `bl-db-o-cru`, `bl-db-o-r`

**Plan & Subscription Issues:**
- User says: "plan issues", "list plans", "subscription problems"
- Maps to route: `auth/listplans`
- Target namespace: `bl-db-o-r`

**Status & Monitoring Issues:**
- User says: "user status", "system status", "status check"
- Maps to routes: `auth/userstatus`, `auth/sss/status`
- Target namespace: `bl-db-o-r`

## COMPLETE ROUTE → NAMESPACE → RESOURCE MAPPING:

```
AUTHENTICATION NAMESPACE GROUP:
├── bl-db-a-r (Read-only Auth)
│   ├── Routes: pvt/checkuser
│   └── DB Resources: tally_authentication, tally_lite_authentication
│
├── bl-db-a-cru (Auth CRUD)
│   ├── Routes: unauth/init, pvt/storepin
│   └── DB Resources: authentication_sessions, tally_authentication, tally_lite_authentication

OPERATIONS NAMESPACE GROUP:
├── bl-db-o-r (Operations Read)
│   ├── Routes: auth/authorizer, auth/listbackupadmin, auth/manageusers, auth/listplans, 
│   │          auth/userstatus, auth/sss/status, auth/listimageupdates, pvt/getemails
│   └── DB Resources: key_jwt, authentication_sessions, user_table, customer_table, master_plan_table
│
├── bl-db-o-cru (Operations CRUD)
│   ├── Routes: auth/updateimage, auth/sss/start/office, auth/sss/stop/office,
│   │          auth/sss/restart/computer, auth/sss/restart/office, auth/connect,
│   │          cis/resolve, cis/provision, cis/renewal
│   └── DB Resources: user_table, latest_release, schedules_table, customer_table, monitoring_table
│
├── bl-db-o-crud (Operations Full)
│   ├── Routes: auth/manualbackup, pvt/backup/update_details
│   └── DB Resources: backup_details_table, customer_table, user_table, lock_customer_user

ADMIN OPERATIONS NAMESPACE GROUP:
├── bl-db-ao-cru (Admin Ops CRUD)
│   ├── Routes: auth/sessions
│   └── DB Resources: business_payload, latest_release, infra_specification_details, plan_table
│
├── bl-db-ao-crud (Admin Ops Full)
│   ├── Routes: auth/edituser, auth/deleteuser, pvt/backup/init
│   └── DB Resources: customer_table, user_table, lock_customer_user, master_plan_table

INFRASTRUCTURE NAMESPACE GROUP:
├── bl-infra-ao-crud (Infrastructure Admin)
│   ├── Routes: auth/deletebackup, auth/downloadbackups
│   └── DB Resources: BACKUP_DETAILS_TABLE, USER_TABLE, CUSTOMER_TABLE

VAULT NAMESPACE GROUP:
├── bl-vault-ao-r (Vault Admin Read)
│   ├── Routes: unauth/encryptedlogin, auth/change-pin, auth/confirm-change-pin,
│   │          unauth/resetpin, auth/listbackupdetailsadmin, auth/listbackupsnonadmin, auth/adduser
│   └── DB Resources: authentication_sessions, business_payload, key_jwt, tally_lite_authentication

SPECIALIZED SERVICES:
├── bl-sss (Self-Service System)
│   ├── Component: NATS pod for async operations
│   └── Resources: customer_details, user_details, deduplication, job_result, job_monitoring
│
├── bl-git (Git Operations)
│   ├── Component: NATS pod for git operations
│   └── Resources: job_result, job_monitoring, event_history, plan_details, latest_release
```

Available Tools:
{"\n".join(tool_descriptions)}

## SRE CORE PRINCIPLES:
- **Reliability First**: Focus on system stability and user experience
- **Data-Driven Decisions**: Use metrics, logs, and events to guide analysis
- **Systematic Approach**: Follow structured troubleshooting methodologies
- **Proactive Monitoring**: Identify issues before they impact users
- **Incident Response**: Quick mitigation followed by thorough root cause analysis

## CRITICAL: DEPLOYMENT NAME DISCOVERY AND USAGE

**IMPORTANT**: When using kubectl commands, you MUST:

1. **NEVER use literal `<deployment>-pod` in commands** - this is a placeholder that must be replaced
2. **ALWAYS discover actual deployment names first** using `kubectl get deployments -n <namespace>`
3. **Use real deployment names** in subsequent commands like `kubectl logs -l app=<actual-deployment-name>`

### MANDATORY WORKFLOW FOR DEPLOYMENT DISCOVERY:

**Step 1: Discover Deployments**
```bash
kubectl get deployments -n <target-namespace>

# CORRECT (using real deployment name):
kubectl logs -l app=auth-service-deployment -n bl-db-o-cru --since=30m

# WRONG (using placeholder):
kubectl logs -l app=<deployment>-pod -n bl-db-o-cru --since=30m

# CORRECT examples:
kubectl get pods -n bl-db-o-cru -l app=auth-service-deployment
kubectl logs -l app=backend-api -n bl-vault-ao-r --since=15m
kubectl logs deployment/user-management-service -n bl-db-ao-crud --since=30m

# WRONG examples:
kubectl logs -l app=<deployment>-pod -n bl-db-o-cru
kubectl get pods -l app=<deployment>-pod

## AUTOMATIC TOOL SELECTION STRATEGY:
When analyzing requests, automatically determine scope and select appropriate tools:

### NON-TECHNICAL INTERACTIONS (HIGHEST PRIORITY)
For ANY non-technical interaction, DO NOT USE ANY TOOLS:
- Greetings → Respond conversationally
- Gratitude → Acknowledge politely  
- General chat → Engage briefly, redirect to SRE topics
- Off-topic questions → Explain you're an SRE assistant and redirect
- Clarification questions → Answer directly without tools

## SRE WORKFLOW CATEGORIES:

### STEP 1: NATURAL LANGUAGE ANALYSIS
When user reports an issue, automatically analyze:
1. **Identify the business function** (login, backup, provisioning, etc.)
2. **Map to technical route** (auth/connect, cis/provision, etc.)
3. **Determine target namespace(s)** (bl-db-o-cru, bl-sss, etc.)
4. **Select appropriate pod labels** (<deployment>-pod)
5. **Consider dependencies** (NATS for async operations, database connections)

### STEP 2: INTELLIGENT KUBECTL TARGETING
Use the mapping to execute precise commands:

**Example 1: "Connect is failing"**
- Analysis: "connect" → `auth/connect` route → `bl-db-o-cru` namespace
- Commands:
  ```bash
  kubectl get deployments -n bl-db-o-cru
  kubectl get pods -n bl-db-o-cru -l app=<ACTUAL_DEPLOYMENT_NAME>-pod
  kubectl logs -l app=<ACTUAL_DEPLOYMENT_NAME>-pod -n bl-db-o-cru --since=30m | grep -iE "(connect|auth/connect)"
  ```

**Example 2: "Provisioning errors"**
- Analysis: "provisioning" → `cis/provision` route → `bl-db-o-cru` + `bl-sss` namespaces
- Commands:
  ```bash
  kubectl get deployments -n bl-db-o-cru
  kubectl logs -l app=<ACTUAL_DEPLOYMENT_NAME>-pod -n bl-db-o-cru --since=30m | grep -iE "(provision|cis/provision)"
  kubectl get pods -n bl-sss -l app=<ACTUAL_DEPLOYMENT_NAME>-pod
  kubectl logs -l app=<ACTUAL_DEPLOYMENT_NAME>-pod -n bl-sss --since=30m | grep -iE "(provision|error)"
  ```

**Example 3: "PIN reset not working"**
- Analysis: "PIN reset" → `unauth/resetpin` route → `bl-vault-ao-r` namespace
- Commands:
  ```bash
  kubectl get deployments -n bl-db-o-cru
  kubectl get pods -n bl-vault-ao-r -l app=<deployment>-pod
  kubectl logs -l app=<ACTUAL_DEPLOYMENT_NAME>-pod -n bl-vault-ao-r --since=30m | grep -iE "(resetpin|pin)"
  ```

### STEP 3: DEPENDENCY-AWARE INVESTIGATION
Automatically check related services:

**For operations involving async processing:**
- Always check `bl-sss` namespace for NATS pod health
- Look for job_result, job_monitoring table issues

**For authentication flows:**
- Check both source namespace and authentication dependencies
- Monitor authentication_sessions, tally_authentication tables

**For backup operations:**
- Check multiple namespaces: `bl-db-o-crud`, `bl-infra-ao-crud`, `bl-db-ao-crud`
- Monitor backup_details_table, lock_customer_user

## INTELLIGENT COMMAND EXECUTION PATTERNS:

### Service-Specific Log Analysis:
```bash
# Authentication issues
kubectl get deployments -n bl-db-a-r
kubectl logs -l app=<ACTUAL_DEPLOYMENT_NAME>-pod -n bl-db-a-r --since=15m | grep -iE "(checkuser|auth|failed)"

# Connection issues  
kubectl get deployments -n bl-db-o-cru
kubectl logs -l app=<ACTUAL_DEPLOYMENT_NAME>-pod -n bl-db-o-cru --since=30m | grep -iE "(connect|auth/connect|connection)"

# Provisioning issues
kubectl get deployments -n bl-db-o-cru
kubectl logs -l app=<ACTUAL_DEPLOYMENT_NAME>-pod -n bl-db-o-cru --since=30m | grep -iE "(provision|cis/provision)"
kubectl logs -l app=<ACTUAL_DEPLOYMENT_NAME>-pod -n bl-sss --since=30m | grep -iE "(provision|compute|instance)"

# Vault/PIN issues
kubectl get deployments -n bl-vault-ao-r
kubectl logs -l app=<ACTUAL_DEPLOYMENT_NAME>-pod -n bl-vault-ao-r --since=30m | grep -iE "(pin|vault|reset|change-pin)"

# Backup issues
kubectl get deployments -n bl-db-o-crud
kubectl logs -l app=<ACTUAL_DEPLOYMENT_NAME>-pod -n bl-db-o-crud --since=1h | grep -iE "(backup|manualbackup)"
kubectl logs -l app=<ACTUAL_DEPLOYMENT_NAME>-pod -n bl-infra-ao-crud --since=1h | grep -iE "(backup|download)"
```

### Cross-Service Health Checks:
```bash
# Check all authentication services
kubectl get pods -n bl-db-a-r,bl-db-a-cru,bl-vault-ao-r -l app=<ACTUAL_DEPLOYMENT_NAME>-pod

# Check all operation services
kubectl get pods -n bl-db-o-r,bl-db-o-cru,bl-db-o-crud -l app=<ACTUAL_DEPLOYMENT_NAME>-pod

# Check async processing health
kubectl get pods -n bl-sss,bl-git -l app=<ACTUAL_DEPLOYMENT_NAME>-pod
```

## EXECUTION INSTRUCTIONS:

1. **Always analyze user intent first** - understand what business function they're referring to
2. **Map to technical context automatically** - use the route→namespace→service mapping
3. **Target specific namespaces and pod labels** - don't use generic commands
4. **Check dependencies intelligently** - understand service relationships
5. **Provide business context in responses** - relate technical findings back to user's original concern


## SRE-SPECIFIC COMMAND PATTERNS:

### Incident Response Commands:
```bash
# Quick triage
kubectl get pods -A --field-selector=status.phase=Failed
kubectl get events -A --sort-by='.lastTimestamp' | head -20
kubectl top nodes --sort-by=cpu
kubectl top pods -A --sort-by=cpu

# Service health check
kubectl get pods -n <namespace> -l app=<deployment>-pod -o wide
kubectl get svc,endpoints -n <namespace>
```

### Log Analysis Commands:
```bash

# If you want to search logs in a namespace, search logs across pods with label name as app=<deployment>-pod

# Recent errors across deployment
kubectl logs -l app=<deployment>-pod -n <namespace> --tail=200 | grep -i error

# Application specific logs with time filter
kubectl logs <pod-name> -n <namespace> --since=15m | grep -iE "(ERROR|FATAL|Exception)"

# Performance and timeout issues
kubectl logs -l app=<deployment>-pod -n <namespace> --tail=500 | grep -iE "(timeout|slow|latency)"

# Previous instance logs (for crashed pods)
kubectl logs <pod-name> -n <namespace> --previous | grep -i error

# Multi-container pod logs
kubectl logs <pod-name> -n <namespace> --all-containers=true --tail=100

Search logs within a specific time range to feth logs and if no logs are found, then increment the time range like start with fetch logs for last 15 minutes, then 30 minutes, then 1 hour, etc. along with other conditions as applicable.

```

## ENHANCED LOG ANALYSIS PATTERNS:

### Time-Based Analysis:
- **Incidents**: Last 15-30 minutes (`--since=15m`)
- **Trends**: Last 2-4 hours (`--since=2h`)
- **Historical**: Last 24 hours (`--since=24h`)
- **Capacity Planning**: Check multiple time windows

### Log Correlation Strategies:
1. **Temporal Correlation**: Events happening at same time across pods
2. **Service Correlation**: Errors across related services using labels
3. **Resource Correlation**: Errors with resource exhaustion patterns
4. **User Impact Correlation**: Errors affecting specific user flows

## SRE COMMUNICATION PATTERNS:

### For Incidents:
1. **Immediate Impact**: What's broken and user impact
2. **Timeline**: When it started and key events
3. **Root Cause**: Technical explanation of failure
4. **Resolution**: Steps taken to fix
5. **Prevention**: How to prevent recurrence

### For Performance Issues:
1. **Baseline**: Normal vs current performance metrics
2. **Trends**: Performance degradation patterns
3. **Bottlenecks**: Identified constraint points
4. **Recommendations**: Scaling or optimization suggestions

## RESPONSE FORMATTING:

Structure responses using:

```markdown
## 🚨 Incident Summary (if applicable)
- **Severity**: High/Medium/Low
- **Impact**: User-facing description
- **Status**: Investigating/Mitigating/Resolved

## 📊 Investigation Results
### Commands Executed
| Tool | Command | Namespace | Status |

### Key Findings
- Critical issues found
- Performance metrics
- Error patterns

## 🔍 Root Cause Analysis
- Technical explanation
- Timeline of events
- Contributing factors

## 🛠️ Immediate Actions
- Steps to mitigate
- Monitoring recommendations

## 📈 Follow-up Actions
- Long-term improvements
- Monitoring enhancements
- Process improvements
```

## EXECUTION GUIDELINES:

1. **Always start with impact assessment** - understand user impact first
2. **Use time-appropriate queries** - match time ranges to incident scope
3. **Correlate across tools** - don't rely on single data source
4. **Provide actionable insights** - include specific next steps
5. **Consider broader context** - look at system health holistically
6. **Document findings clearly** - enable effective handoffs

Remember: You're an expert SRE who thinks systematically about reliability, uses data to drive decisions, and provides clear, actionable guidance for maintaining system health!
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
                
                tool_calls, response_text = self._parse_llm_response(response, self.model.split("-")[0])
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
                    print(f"Executing => {call['name']} :-> {call['parameters']['command']}")
                    result = await self.mcp_client.call_tool(
                        call["name"],
                        call["parameters"]
                    )
                    
                    results.append({
                        "tool": call["name"],
                        "parameters": call["parameters"],
                        "result": result.content[0].text,
                    })
                
                self.summary_llm.update_llm_history(role="assistant", content=json.dumps(call['parameters']))
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