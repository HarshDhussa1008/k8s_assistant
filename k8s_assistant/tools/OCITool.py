import subprocess
import json
from typing import Any, Dict
from k8s_assistant.tools.Tool import Tool


class OCITool(Tool):
    """
    Class to interact with Oracle Cloud Infrastructure using OCI CLI.
    """

    def __init__(self):
        super().__init__("OCITool")
    
    def run(
        self,
        command: str,
        compartment_id: str = None,
        output_format: str = "json"
    ) -> Dict[str, Any]:
        """
        Execute an OCI CLI command against Oracle Cloud Infrastructure.
        
        Args:
            command: The OCI CLI command to execute (without 'oci' prefix)
            compartment_id: Optional compartment ID to scope the command
            output_format: Output format (json, table, text)
        """
        
        # Define forbidden commands for security
        forbidden_keywords = [
            "delete", "terminate", "destroy", "remove", "purge",
            "update", "modify", "change", "edit", "patch",
            "create", "launch", "deploy", "provision",
            "start", "stop", "restart", "reboot", "reset"
        ]
        
        if any(keyword in command.lower() for keyword in forbidden_keywords):
            return {
                "stderr": "This command is not allowed for security reasons. Only read-only operations are permitted.",
                "stdout": "",
                "code": 403,
                "status": "forbidden"
            }
        
        # Build the full OCI command
        if not command.startswith("oci "):
            cmd = f"oci {command}"
        else:
            cmd = command
        
        # Add compartment ID if provided and not already in command
        if compartment_id and '--compartment-id' not in command:
            cmd += f" --compartment-id {compartment_id}"
        
        # Add output format if not already specified
        if '--output' not in command and output_format:
            cmd += f" --output {output_format}"
        
        print(f"Executing OCI command: {cmd}")
        
        try:
            result = subprocess.run(
                cmd.split(), 
                capture_output=True, 
                text=True,
                check=False,
                timeout=30  # Timeout after 30 seconds for cloud operations
            )
            
            # Try to parse JSON output for better formatting
            stdout_parsed = result.stdout
            if output_format == "json" and result.stdout:
                try:
                    parsed_json = json.loads(result.stdout)
                    stdout_parsed = json.dumps(parsed_json, indent=2)
                except json.JSONDecodeError:
                    # If not valid JSON, keep original output
                    stdout_parsed = result.stdout
            
            return {
                "stdout": stdout_parsed,
                "stderr": result.stderr,
                "status": "success" if result.returncode == 0 else "error",
                "code": result.returncode
            }
        
        except subprocess.TimeoutExpired:
            return {
                "error": "Command timed out after 30 seconds", 
                "status": "timeout",
                "command": cmd
            }
        except Exception as e:
            return {
                "error": str(e), 
                "status": "exception",
                "command": cmd
            }
