"""Generic adapter factory."""
from .adapters import A2AAgentAdapter, ExternalWebhookAgentAdapter, LangGraphAgentAdapter, PythonFunctionAgentAdapter, RestApiAgentAdapter

ADAPTER_TYPES = {
    "python_function": PythonFunctionAgentAdapter,
    "langgraph": LangGraphAgentAdapter,
    "rest_api": RestApiAgentAdapter,
    "external_webhook": ExternalWebhookAgentAdapter,
    "a2a": A2AAgentAdapter,
}

def build_adapter(contract, services=None): return ADAPTER_TYPES[contract.adapter_type](contract, services)
