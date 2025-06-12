import os
import subprocess
from typing import Any, Dict
from k8s_assistant.tools.Tool import Tool


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
        
        cmd = f"kubectl {command}"
        
        if namespace and '-n' not in command:
            cmd += f" -n {namespace}"
        print(f"Executing command: {cmd}")
        
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
                cmd.split(), 
                capture_output=True, 
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
                "code": result.returncode
            }
        
        except subprocess.TimeoutExpired:
            return {"error": "Command timed out", "status": "timeout"}
        except Exception as e:
            return {"error": str(e), "status": "exception"}
