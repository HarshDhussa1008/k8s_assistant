import json
import os
import subprocess
from typing import Any, Dict
from k8s_assistant.tools.Tool import Tool
from opensearchpy import OpenSearch, RequestsHttpConnection
from opensearchpy.exceptions import OpenSearchException, ConnectionError, AuthenticationException


class OpensearchTool(Tool):
    """
    Class to interact with OpenSearch using the OpenSearch CLI.
    This tool allows executing read-only commands against an OpenSearch cluster.
    """

    def __init__(self):
        super().__init__("OpensearchTool")
        self.opensearch_host = os.getenv("OPENSEARCH_HOST", "localhost")
        self.opensearch_port = int(os.getenv("OPENSEARCH_PORT", 443))
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
            'retry_on_timeout': False,
            'connection_class': RequestsHttpConnection
        }
        
        client = OpenSearch(**client_config)
        
        try:
            health = client.cluster.health()
            print("✅ Connection successful!")
            print(f"Cluster status: {health['status']}")
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            raise ConnectionError(f"Failed to connect to OpenSearch: {e} \n Please check your connection settings {client_config}.")
        
        return client
    
    def _extract_search_terms(self, query_obj):
        """Extract searchable terms from a complex query object."""
        if not isinstance(query_obj, dict):
            return str(query_obj)
    
        terms = []
        def extract_from_query(q):
            if isinstance(q, dict):
                for key, value in q.items():
                    if key in ['term', 'match', 'match_phrase']:
                        if isinstance(value, dict):
                            for field, term_value in value.items():
                                if isinstance(term_value, (str, int, float)):
                                    terms.append(str(term_value))
                    elif key in ['must', 'should', 'filter']:
                        if isinstance(value, list):
                            for item in value:
                                extract_from_query(item)
                        else:
                            extract_from_query(value)
                    elif key == 'bool':
                        extract_from_query(value)
            
        extract_from_query(query_obj)
        return ' '.join(terms) if terms else "*"
    
    def run(
        self,
        index: str = "k8s-logs-*",
        command: dict = None,
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
            
            query = command.get('query', None) if command else None
            
            if not query:
                body = {
                    "query": {"match_all": {}},
                    "size": 10
                }
            else:
                body = command
            
            # Execute the search query
            response = self.client.search(index=index, body=body)
            
            total_hits = response['hits']['total']
            if isinstance(total_hits, dict):
                hit_count = total_hits['value']
            else:
                hit_count = total_hits
            
            if hit_count > 0:
                return {
                    "stdout": response,
                    "stderr": "",
                    "code": 200,
                    "status": "success"
                }
            else:
                search_terms = self._extract_search_terms(query) if query else "*"
                fallback_body = {
                    "query": {
                        "multi_match": {
                            "query": search_terms,
                            "fields": [
                                "log",        # Boost log field  
                                "*"             # Search all fields
                            ],
                            "type": "best_fields"
                        }
                    },
                    "size": body.get("size", 10),
                    "sort": [{"timestamp": {"order": "desc"}}]
                }
                response = self.client.search(index=index, body=fallback_body)
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
    
        
        