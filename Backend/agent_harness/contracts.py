"""Portable agent contracts for the reusable control-plane framework."""
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class AgentStatus(str, Enum):
    ACTIVE = "active"
    REVIEW = "review"
    DISABLED = "disabled"
    QUARANTINED = "quarantined"


class RiskTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RuntimeType(str, Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    WORKFLOW = "workflow"
    SERVICE = "service"


class AdapterType(str, Enum):
    PYTHON_FUNCTION = "python_function"
    LANGGRAPH = "langgraph"
    REST_API = "rest_api"
    EXTERNAL_WEBHOOK = "external_webhook"
    A2A = "a2a"


class ExecutionMode(str, Enum):
    WORKFLOW = "workflow"
    SYNCHRONOUS = "synchronous"
    DECOUPLED = "decoupled"
    ASYNC = "async"
    STREAMING = "streaming"


class ModelProvider(str, Enum):
    GROQ = "groq"
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    BEDROCK = "bedrock"
    LOCAL = "local"
    EXTERNAL = "external"
    NONE = "none"
    UNKNOWN = "unknown"


class BudgetPeriod(str, Enum):
    INVOCATION = "invocation"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class BudgetEnforcementMode(str, Enum):
    DISABLED = "disabled"
    MONITOR = "monitor"
    WARN = "warn"
    ENFORCE = "enforce"
    HARD_BLOCK = "hard_block"


SUPPORTED_CONTRACT_VERSION = "2.0.0"
LEGACY_CONTRACT_VERSION = "1.0.0"


_SECTION_KEYS = {
    "identity", "runtime", "schemas", "capabilities", "model_policy", "permissions",
    "budget_policy", "observability", "lifecycle",
}


_LEGACY_KEYS = {
    "agent_id", "name", "display_name", "owner", "business_function", "risk_tier",
    "agent_type", "execution_mode", "adapter_type", "entrypoint", "endpoint", "version",
    "original_contract_version", "contract_version", "description", "input_schema", "output_schema", "state_schema",
    "memory_schema", "skills", "tools", "memory_contracts", "prompts", "evaluators",
    "hooks", "model_preferences", "policy_permissions", "guardrails",
    "observability_hooks", "status", "metadata", "runtime_type", "timeout_seconds",
    "retry_policy", "health_check", "budget_policy", "degradation_policy",
    "recovery_policy", "validation_result", "unresolved_references",
}


_SENSITIVE_KEY_FRAGMENTS = ("api_key", "apikey", "password", "passwd", "secret", "token", "bearer")


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _merge_dict(*items):
    merged = {}
    for item in items:
        if isinstance(item, dict):
            merged.update(item)
    return merged


def _enum_value(enum_cls, value, default=None):
    value = default if value in (None, "") else value
    if value in (None, ""):
        return value
    return enum_cls(value).value


def _detect_inline_secret(value: Any, path: str = "") -> list[str]:
    findings = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            key_lower = str(key).lower()
            if any(fragment in key_lower for fragment in _SENSITIVE_KEY_FRAGMENTS):
                if isinstance(child, str) and child and not child.startswith(("env:", "secret:", "credential:")) and not child.isupper():
                    findings.append(child_path)
            findings.extend(_detect_inline_secret(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_detect_inline_secret(child, f"{path}[{index}]"))
    return findings


@dataclass
class AgentContract:
    agent_id: str
    name: str
    owner: str
    business_function: str
    agent_type: str
    execution_mode: str
    adapter_type: str
    entrypoint: str = ""
    endpoint: str = ""
    version: str = "1.0.0"
    original_contract_version: str = LEGACY_CONTRACT_VERSION
    contract_version: str = SUPPORTED_CONTRACT_VERSION
    description: str = ""
    risk_tier: str = RiskTier.MEDIUM.value
    runtime_type: str = RuntimeType.INTERNAL.value
    timeout_seconds: int | None = None
    retry_policy: dict[str, Any] = field(default_factory=dict)
    health_check: dict[str, Any] = field(default_factory=dict)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    state_schema: dict[str, Any] = field(default_factory=dict)
    memory_schema: dict[str, Any] = field(default_factory=dict)
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    memory_contracts: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    evaluators: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    model_preferences: dict[str, Any] = field(default_factory=dict)
    policy_permissions: dict[str, Any] = field(default_factory=dict)
    budget_policy: dict[str, Any] = field(default_factory=dict)
    guardrails: list[str] = field(default_factory=list)
    observability_hooks: dict[str, Any] = field(default_factory=dict)
    degradation_policy: dict[str, Any] = field(default_factory=dict)
    recovery_policy: dict[str, Any] = field(default_factory=dict)
    status: AgentStatus = AgentStatus.ACTIVE
    metadata: dict[str, Any] = field(default_factory=dict)
    validation_result: dict[str, Any] = field(default_factory=lambda: {"valid": True, "errors": [], "warnings": []})
    unresolved_references: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw):
        raw = deepcopy(raw or {})
        sectioned = any(key in raw for key in {"identity", "runtime", "schemas", "capabilities", "model_policy", "permissions", "lifecycle"})
        allowed = _SECTION_KEYS | _LEGACY_KEYS
        unknown = sorted(key for key in raw if key not in allowed)
        if unknown:
            raise ValueError(f"Unknown contract field(s): {', '.join(unknown)}")

        values = cls._from_sectioned(raw) if sectioned else cls._from_legacy(raw)

        for enum_cls, field_name, default in (
            (RiskTier, "risk_tier", RiskTier.MEDIUM.value),
            (RuntimeType, "runtime_type", RuntimeType.INTERNAL.value),
            (ExecutionMode, "execution_mode", None),
            (AdapterType, "adapter_type", None),
        ):
            values[field_name] = _enum_value(enum_cls, values.get(field_name), default)

        values["status"] = AgentStatus(values.get("status", AgentStatus.ACTIVE.value))
        values["skills"] = _as_list(values.get("skills"))
        values["tools"] = _as_list(values.get("tools"))
        values["memory_contracts"] = _as_list(values.get("memory_contracts"))
        values["prompts"] = _as_list(values.get("prompts"))
        values["evaluators"] = _as_list(values.get("evaluators"))
        values["hooks"] = _as_list(values.get("hooks"))
        values["guardrails"] = _as_list(values.get("guardrails"))
        permissions = values.get("policy_permissions")
        if isinstance(permissions, dict) and "human_approval_required_for" in permissions and "requires_human_approval_for" not in permissions:
            permissions["requires_human_approval_for"] = permissions["human_approval_required_for"]
        if values.get("timeout_seconds") is not None:
            values["timeout_seconds"] = int(values["timeout_seconds"])

        secret_paths = _detect_inline_secret(raw)
        if secret_paths:
            raise ValueError("Contract contains inline secret-looking values at: " + ", ".join(secret_paths))

        known = set(cls.__dataclass_fields__)
        values = {key: value for key, value in values.items() if key in known}
        return cls(**values)

    @staticmethod
    def _from_legacy(raw):
        metadata = dict(raw.get("metadata") or {})
        values = {key: value for key, value in raw.items() if key in _LEGACY_KEYS and key != "metadata"}
        values["metadata"] = metadata
        original = str(raw.get("original_contract_version") or raw.get("contract_version") or raw.get("version") or LEGACY_CONTRACT_VERSION)
        values["original_contract_version"] = original
        values["contract_version"] = SUPPORTED_CONTRACT_VERSION
        values["version"] = str(raw.get("version") or original)
        if "display_name" in raw and "name" not in values:
            values["name"] = raw["display_name"]
        values["timeout_seconds"] = raw.get("timeout_seconds", metadata.pop("timeout_seconds", None))
        values["retry_policy"] = raw.get("retry_policy") or metadata.pop("retry", {})
        values["budget_policy"] = raw.get("budget_policy") or values.get("policy_permissions", {}).get("budget_policy", {})
        values["degradation_policy"] = raw.get("degradation_policy") or {}
        values["recovery_policy"] = raw.get("recovery_policy") or {}
        values["validation_result"] = raw.get("validation_result", {"valid": True, "errors": [], "warnings": []})
        values["unresolved_references"] = raw.get("unresolved_references", {})
        return values

    @staticmethod
    def _from_sectioned(raw):
        identity = raw.get("identity") or {}
        runtime = raw.get("runtime") or {}
        schemas = raw.get("schemas") or {}
        capabilities = raw.get("capabilities") or {}
        model_policy = raw.get("model_policy") or {}
        permissions = raw.get("permissions") or {}
        budget_policy = raw.get("budget_policy") or {}
        observability = raw.get("observability") or {}
        lifecycle = raw.get("lifecycle") or {}
        values = {
            "agent_id": identity.get("agent_id"),
            "name": identity.get("display_name") or identity.get("name"),
            "owner": identity.get("owner"),
            "business_function": identity.get("business_function"),
            "risk_tier": identity.get("risk_tier", RiskTier.MEDIUM.value),
            "agent_type": identity.get("agent_type"),
            "version": str(identity.get("contract_version") or raw.get("version") or SUPPORTED_CONTRACT_VERSION),
            "original_contract_version": str(identity.get("contract_version") or raw.get("contract_version") or SUPPORTED_CONTRACT_VERSION),
            "contract_version": SUPPORTED_CONTRACT_VERSION,
            "description": identity.get("description") or raw.get("description", ""),
            "runtime_type": runtime.get("runtime_type", RuntimeType.INTERNAL.value),
            "adapter_type": runtime.get("adapter_type"),
            "execution_mode": runtime.get("execution_mode"),
            "entrypoint": runtime.get("entrypoint", ""),
            "endpoint": runtime.get("endpoint", ""),
            "timeout_seconds": runtime.get("timeout_seconds"),
            "retry_policy": runtime.get("retry_policy") or {},
            "health_check": runtime.get("health_check") or {},
            "input_schema": schemas.get("input_schema") or {},
            "output_schema": schemas.get("output_schema") or {},
            "state_schema": schemas.get("state_schema") or {},
            "memory_schema": schemas.get("memory_schema") or schemas.get("memory_contract_schema") or {},
            "skills": capabilities.get("skills") or [],
            "tools": capabilities.get("tools") or [],
            "memory_contracts": capabilities.get("memory_contracts") or [],
            "prompts": capabilities.get("prompts") or [],
            "evaluators": capabilities.get("evaluators") or [],
            "hooks": capabilities.get("hooks") or [],
            "model_preferences": model_policy,
            "policy_permissions": permissions,
            "budget_policy": budget_policy,
            "observability_hooks": observability,
            "status": lifecycle.get("initial_status", lifecycle.get("status", AgentStatus.ACTIVE.value)),
            "degradation_policy": lifecycle.get("degradation_policy") or {},
            "recovery_policy": lifecycle.get("recovery_policy") or {},
            "metadata": raw.get("metadata") or {},
        }
        if raw.get("guardrails"):
            values["guardrails"] = raw["guardrails"]
        return values

    def to_dict(self):
        result = asdict(self)
        result["status"] = self.status.value
        return result

    def effective_contract(self):
        """Return the resolved sectioned contract shape exposed by registry APIs."""
        permissions = _merge_dict(self.policy_permissions)
        model_policy = _merge_dict(self.model_preferences)
        observability = _merge_dict(self.observability_hooks)
        return {
            "identity": {
                "agent_id": self.agent_id,
                "display_name": self.name,
                "owner": self.owner,
                "business_function": self.business_function,
                "risk_tier": self.risk_tier,
                "agent_type": self.agent_type,
                "contract_version": self.contract_version,
                "description": self.description,
            },
            "runtime": {
                "runtime_type": self.runtime_type,
                "adapter_type": self.adapter_type,
                "execution_mode": self.execution_mode,
                "entrypoint": self.entrypoint or None,
                "endpoint": self.endpoint or None,
                "timeout_seconds": self.timeout_seconds,
                "retry_policy": self.retry_policy,
                "health_check": self.health_check,
            },
            "schemas": {
                "input_schema": self.input_schema,
                "output_schema": self.output_schema,
                "state_schema": self.state_schema,
                "memory_schema": self.memory_schema,
            },
            "capabilities": {
                "skills": self.skills,
                "tools": self.tools,
                "memory_contracts": self.memory_contracts,
                "prompts": self.prompts,
                "evaluators": self.evaluators,
                "hooks": self.hooks,
            },
            "model_policy": {
                "provider": model_policy.get("provider") or model_policy.get("llm_provider") or ModelProvider.UNKNOWN.value,
                "deployment": model_policy.get("deployment") or model_policy.get("primary") or model_policy.get("llm_model"),
                "allowed_fallbacks": model_policy.get("allowed_fallbacks") or _as_list(model_policy.get("fallback")),
                "temperature": model_policy.get("temperature"),
                "max_output_tokens": model_policy.get("max_output_tokens"),
                "supports_tools": model_policy.get("supports_tools", False),
                "supports_structured_output": model_policy.get("supports_structured_output", False),
                **{k: v for k, v in model_policy.items() if k not in {"provider", "llm_provider", "deployment", "primary", "llm_model", "allowed_fallbacks", "fallback"}},
            },
            "permissions": {
                "allowed_actions": permissions.get("allowed_actions", []),
                "allowed_tools": permissions.get("allowed_tools", []),
                "allowed_data_scopes": permissions.get("allowed_data_scopes", []),
                "denied_actions": permissions.get("denied_actions", []),
                "human_approval_required_for": permissions.get("human_approval_required_for", permissions.get("requires_human_approval_for", [])),
                "mcp_servers": permissions.get("mcp_servers", []),
                "mcp_tools": permissions.get("mcp_tools", []),
                **{k: v for k, v in permissions.items() if k not in {"allowed_actions", "allowed_tools", "allowed_data_scopes", "denied_actions", "human_approval_required_for", "requires_human_approval_for", "mcp_servers", "mcp_tools"}},
            },
            "guardrails": self.guardrails,
            "budget_policy": self.budget_policy,
            "observability": {
                "trace_enabled": observability.get("trace_enabled", observability.get("execution_trace", False)),
                "audit_enabled": observability.get("audit_enabled", observability.get("audit", False)),
                "usage_enabled": observability.get("usage_enabled", observability.get("usage_cost", False)),
                "step_events_enabled": observability.get("step_events_enabled", observability.get("step_trace", False)),
                "heartbeat_required": observability.get("heartbeat_required", observability.get("heartbeat", False)),
                "heartbeat_ttl_seconds": observability.get("heartbeat_ttl_seconds"),
                "external_event_ingestion_enabled": observability.get("external_event_ingestion_enabled", observability.get("event_ingestion", False)),
                "event_schema_version": observability.get("event_schema_version", "1.0"),
                "hooks": observability,
            },
            "lifecycle": {
                "initial_status": self.status.value,
                "degradation_policy": self.degradation_policy,
                "recovery_policy": self.recovery_policy,
            },
            "metadata": self.metadata,
        }


AgentManifest = AgentContract
AgentPluginContract = AgentContract
