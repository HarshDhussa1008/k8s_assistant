import json
import os
import subprocess
from typing import Any, Dict
from k8s_assistant.tools.Tool import Tool
from opensearchpy import OpenSearch
from opensearchpy.exceptions import OpenSearchException, ConnectionError, AuthenticationException


class OpensearchTool(Tool):
    """
    Class to interact with OpenSearch using the OpenSearch CLI.
    This tool allows executing read-only commands against an OpenSearch cluster.
    """

    def __init__(self):
        super().__init__("OpensearchTool")
        self.opensearch_host = os.getenv("OPENSEARCH_HOST", "localhost")
        self.opensearch_port = int(os.getenv("OPENSEARCH_PORT", 9200))
        self.opensearch_user = os.getenv("OPENSEARCH_USER", "admin")
        self.opensearch_password = os.getenv("OPENSEARCH_PASSWORD", "admin")
        self.opensearch_scheme = os.getenv("OPENSEARCH_SCHEME", "https")
        self.verify_ssl = os.getenv("OPENSEARCH_VERIFY_SSL", "false").lower() == "true"
        self.client = self._initialize_client()
    
    def _initialize_client(self) -> OpenSearch:
        """Initialize the OpenSearch client."""
        
        auth = (self.opensearch_user, self.opensearch_password)
        
        client_config = {
            'hosts': [{'host': self.opensearch_host, 'port': self.opensearch_port}],
            'http_auth': auth,
            'use_ssl': self.opensearch_scheme == 'https',
            'verify_certs': self.verify_ssl,
            'ssl_assert_hostname': False,
            'ssl_show_warn': False,
            'timeout': 30,
            'max_retries': 1,
            'retry_on_timeout': False
        }
        
        return OpenSearch(**client_config)
    
    def run(
        self,
        index: str = None,
        query: str = None,
    ) -> Dict[str, Any]:
        """
        Execute an OpenSearch command against the OpenSearch cluster.
        """
        
        try:
            
            if not index:
                return {
                    "stderr": "Index is required.",
                    "stdout": "",
                    "code": 400,
                    "status": "bad_request"
                }
            
            if not query:
                body = {
                    "query": {"match_all": {}},
                    "size": 10
                }
            else:
                body = json.loads(query)
            
            # Execute the search query
            response = self.client.search(index=index, body=body)
            
            return {
                "stdout": response,
                "stderr": "",
                "code": 200,
                "status": "success"
            }
        
        except AuthenticationException as e:
            return {
                "error": f"Authentication failed: {str(e)}",
                "status": "auth_error",
                "code": 401
            }
        except ConnectionError as e:
            return {
                "error": f"Connection failed: {str(e)}",
                "status": "connection_error", 
                "code": 503
            }
        except OpenSearchException as e:
            return {
                "error": f"OpenSearch error: {str(e)}",
                "status": "opensearch_error",
                "code": getattr(e, 'status_code', 500)
            }
        except Exception as e:
            return {
                "error": f"Unexpected error: {str(e)}",
                "status": "exception",
                "code": 500
            }
    
        
        
