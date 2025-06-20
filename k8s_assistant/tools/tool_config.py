tools = {
    "KubectlTool": {
        "name": "kubectl",
        "description": "Execute a kubectl command against the Kubernetes cluster.",
        "args": {
            "command": {
                "type": str,
                "description": "The kubectl command to execute.",
                "required": True
            },
            "namespace": {
                "type": str,
                "description": "The namespace to use for the kubectl command.",
                "required": False,
                "default": "default"
            },
        }
    },
    "OCITool": {
        "name": "oci_cli",
        "description": "Execute OCI commands against the Oracle Cloud Infrastructure.",
        "args": {
            "command": {
                "type": str,
                "description": "The OCI command to execute.",
                "required": True
            },
            "compartment_id": {
                "type": str,
                "description": "The compartment ID to use for the OCI command.",
                "required": False,
                "default": None
            }
        }
    },
    "OpensearchTool": {
        "name": "opensearch",
        "description": "Execute OpenSearch commands against the OpenSearch cluster.",
        "args": {
            "index": {
                "type": str,
                "description": "The index to query in OpenSearch.",
                "required": True
            },
            "query": {
                "type": str,
                "description": "The OpenSearch query to execute (JSON format).",
                "required": False,
                "default": None
            }
        }
    }
}