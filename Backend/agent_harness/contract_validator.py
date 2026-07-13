"""Application-neutral validation of agent contracts."""
from pathlib import Path
from typing import Any
import yaml

from .contracts import BudgetEnforcementMode, BudgetPeriod, ModelProvider
from .exceptions import ContractValidationError


class ContractValidator:
    REQUIRED = ("agent_id", "name", "owner", "business_function", "agent_type", "execution_mode", "adapter_type", "input_schema", "output_schema", "state_schema", "memory_schema")
    ADAPTERS = {"python_function", "langgraph", "rest_api", "external_webhook", "a2a"}
    LIFECYCLE_STATES = {"active", "review", "disabled", "quarantined"}

    def __init__(self, catalog: dict[str, set[str]] | None = None):
        self.catalog = catalog or {}

    @classmethod
    def from_config_dir(cls, config_dir: str | Path):
        config_dir = Path(config_dir)
        catalog_dir = config_dir.parent if config_dir.name == "agents" else config_dir
        prompt_root = catalog_dir.parent / "prompts"
        return cls(_load_reference_catalog(catalog_dir, prompt_root))

    def validate(self, contract):
        errors = [f"Missing required field: {field}" for field in self.REQUIRED if not getattr(contract, field, None)]
        if contract.adapter_type not in self.ADAPTERS: errors.append(f"Unsupported adapter_type: {contract.adapter_type}")
        if contract.adapter_type in {"python_function", "langgraph"} and not contract.entrypoint: errors.append("Internal adapters require entrypoint")
        if contract.adapter_type in {"rest_api", "external_webhook", "a2a"} and not contract.endpoint: errors.append("External adapters require endpoint")
        errors.extend(self._validate_model_policy(contract))
        errors.extend(self._validate_budget_policy(contract))
        errors.extend(self._validate_permissions(contract))
        errors.extend(self._validate_lifecycle(contract))
        unresolved = self.unresolved_references(contract)
        for kind, values in unresolved.items():
            if values:
                errors.append(f"Unresolved {kind}: {', '.join(values)}")
        contract.unresolved_references = unresolved
        contract.validation_result = {"valid": not errors, "errors": errors, "warnings": []}
        return errors

    def validate_or_raise(self, contract):
        errors = self.validate(contract)
        if errors: raise ContractValidationError(f"Invalid contract '{contract.agent_id}': " + "; ".join(errors))

    def unresolved_references(self, contract):
        unresolved = {
            "skills": self._missing("skills", contract.skills),
            "tools": self._missing("tools", contract.tools),
            "memory_contracts": self._missing("memory_contracts", contract.memory_contracts),
            "prompts": self._missing_prompt_refs(contract.prompts),
            "evaluators": self._missing("evaluators", contract.evaluators),
            "hooks": self._missing("hooks", contract.hooks),
            "mcp_servers": self._missing("mcp_servers", contract.policy_permissions.get("mcp_servers", [])),
            "mcp_tools": self._missing("mcp_tools", contract.policy_permissions.get("mcp_tools", [])),
        }
        return {key: value for key, value in unresolved.items() if value}

    def _missing(self, key, refs):
        known = self.catalog.get(key)
        if known is None:
            return []
        return sorted({ref for ref in refs or [] if ref not in known})

    def _missing_prompt_refs(self, refs):
        known = self.catalog.get("prompts")
        if known is None:
            return []
        missing = []
        for ref in refs or []:
            prompt_id = str(ref).split(":", 1)[0]
            if prompt_id not in known:
                missing.append(ref)
        return sorted(set(missing))

    def _validate_model_policy(self, contract):
        policy = contract.model_preferences or {}
        provider = policy.get("provider") or policy.get("llm_provider")
        if not provider and (policy.get("deployment") or policy.get("primary") or policy.get("llm_model")):
            provider = "unknown"
        if not provider:
            return []
        try:
            ModelProvider(provider)
        except ValueError:
            return [f"Unsupported model provider: {provider}"]
        return []

    def _validate_budget_policy(self, contract):
        policy = contract.budget_policy or {}
        errors = []
        if not policy:
            return errors
        if policy.get("period"):
            try: BudgetPeriod(policy["period"])
            except ValueError: errors.append(f"Unsupported budget period: {policy['period']}")
        if policy.get("enforcement_mode"):
            try: BudgetEnforcementMode(policy["enforcement_mode"])
            except ValueError: errors.append(f"Unsupported budget enforcement_mode: {policy['enforcement_mode']}")
        for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens"):
            try:
                if key in policy and policy[key] is not None and int(policy[key]) < 0:
                    errors.append(f"{key} must be >= 0")
            except (TypeError, ValueError):
                errors.append(f"{key} must be numeric")
        try:
            if policy.get("max_cost") is not None and float(policy["max_cost"]) < 0:
                errors.append("max_cost must be >= 0")
        except (TypeError, ValueError):
            errors.append("max_cost must be numeric")
        warning = policy.get("warning_threshold_pct")
        try:
            if warning is not None and not 0 <= float(warning) <= 100:
                errors.append("warning_threshold_pct must be between 0 and 100")
        except (TypeError, ValueError):
            errors.append("warning_threshold_pct must be numeric")
        try:
            max_in = int(policy.get("max_input_tokens") or 0)
            max_out = int(policy.get("max_output_tokens") or 0)
            max_total = policy.get("max_total_tokens")
            if max_total is not None and max_in + max_out > int(max_total):
                errors.append("max_input_tokens + max_output_tokens cannot exceed max_total_tokens")
        except (TypeError, ValueError):
            pass
        return errors

    def _validate_permissions(self, contract):
        permissions = contract.policy_permissions or {}
        allowed = set(permissions.get("allowed_actions") or [])
        denied = set(permissions.get("denied_actions") or [])
        conflicts = sorted(allowed.intersection(denied))
        if conflicts:
            return ["Conflicting allow/deny permissions: " + ", ".join(conflicts)]
        return []

    def _validate_lifecycle(self, contract):
        errors = []
        if contract.status.value not in self.LIFECYCLE_STATES:
            errors.append(f"Unsupported lifecycle status: {contract.status.value}")
        for label, policy in (("degradation_policy", contract.degradation_policy), ("recovery_policy", contract.recovery_policy)):
            state = (policy or {}).get("target_status") or (policy or {}).get("status")
            if state and state not in self.LIFECYCLE_STATES:
                errors.append(f"Unsupported {label} lifecycle status: {state}")
        return errors


def _yaml(path: Path, default: Any):
    if not path.exists():
        return default
    return yaml.safe_load(path.read_text(encoding="utf-8")) or default


def _ids_from_yaml(config_dir: Path, filename: str, key: str) -> set[str]:
    raw = _yaml(config_dir / filename, {})
    items = raw.get(key, raw) if isinstance(raw, dict) else {}
    return set(items) if isinstance(items, dict) else set()


def _prompt_ids(prompt_root: Path) -> set[str]:
    ids = set()
    if not prompt_root.exists():
        return ids
    for path in prompt_root.glob("**/*.yaml"):
        raw = _yaml(path, {})
        if isinstance(raw, dict) and raw.get("prompt_id"):
            ids.add(str(raw["prompt_id"]))
    return ids


def _load_reference_catalog(config_dir: Path, prompt_root: Path) -> dict[str, set[str]]:
    catalog = {
        "skills": _ids_from_yaml(config_dir, "skills.yaml", "skills"),
        "tools": _ids_from_yaml(config_dir, "tools.yaml", "tools"),
        "memory_contracts": _ids_from_yaml(config_dir, "memory_contracts.yaml", "memory_contracts"),
        "evaluators": _ids_from_yaml(config_dir, "evaluators.yaml", "evaluators"),
        "hooks": _ids_from_yaml(config_dir, "hooks.yaml", "hooks"),
        "prompts": _prompt_ids(prompt_root),
        "mcp_servers": _ids_from_yaml(config_dir, "mcp_servers.yaml", "mcp_servers"),
        "mcp_tools": _ids_from_yaml(config_dir, "mcp_tools.yaml", "mcp_tools"),
    }
    return catalog
