import logging
import os
import subprocess
from typing import Any, Dict
from k8s_assistant.tools.Tool import Tool
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False

# Set up logging configuration
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler = logging.FileHandler(os.path.join(os.path.dirname(__file__), "kubectl.log"), mode='a+')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


class KubectlTool(Tool):
    """
    Class to interact with Kubernetes using kubectl.
    """

    def __init__(self):
        super().__init__("KubectlTool")
    
    def run(
        self,
        command: str, 
        namespace: str = "default"
    ) -> Dict[str, Any]:
        """
        Execute a kubectl command against the Kubernetes cluster.
        """
        
        forbidden_keywords = ["delete", "apply", "patch", "scale", "edit", "rollout restart", "cordon", "uncordon", "drain"]
        if any(keyword in command for keyword in forbidden_keywords):
            return {
                "stderr": "This command is not allowed for security reasons.",
                "stdout": "",
                "code": 403,
                "status": "forbidden"
            }
        
        if 'kubectl ' not in command:
            cmd = f"kubectl {command}"
        else:
            cmd = command
        
        if namespace and ('-n' not in command and '--namespace' not in command):
            cmd += f" -n {namespace}"
        
        if 'logs' in command and 'grep' not in command:
            cmd += " --tail=100"  # Default to last 100 lines of logs
        
        logger.info(f"Executing command: {cmd}")
        
        try:
            
            env = os.environ.copy()
            env["PATH"] = "/home/opc/.local/bin:/home/opc/bin:/usr/share/Modules/bin:/usr/local/bin:/usr/bin:/usr/local/sbin:/usr/sbin"
            cwd = "/home/opc"
            env["HOME"] = "/home/opc"
            env["USER"] = "opc"
            
            if "KUBECONFIG" not in env:
                env["KUBECONFIG"] = "/home/opc/.kube/config"
            
            env["OCI_CLI_AUTH"] = "instance_principal"
            env["OCI_VERSION"] = "3.57.0"
            env["SHELL"] = "/bin/bash"
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                shell=True, 
                text=True,
                check=False,
                timeout=10,  # Timeout after 10 seconds
                env=env,
                cwd=cwd  # Set working directory
            )
            
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "status": "success" if result.returncode == 0 else "error",
                "code": result.returncode,
                "command": cmd,
                "namespace": namespace
            }
        
        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out: {cmd}")
            logger.debug(f"Command: {cmd}")
            return {"error": "Command timed out", "status": "timeout"}
        except Exception as e:
            logger.error(f"Error executing command: {e}")
            logger.debug(f"Command: {cmd}")
            return {"error": str(e), "status": "exception"}
