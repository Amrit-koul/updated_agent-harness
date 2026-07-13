"""Generic YAML loading. Callers must supply their application config path."""
from pathlib import Path
import yaml

from .contracts import AgentContract
from .exceptions import ContractValidationError


def load_yaml(path: str | Path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_agent_contracts(config_dir: str | Path):
    directory = Path(config_dir)
    contracts = []
    for path in sorted(directory.glob("*.yaml")):
        raw = load_yaml(path)
        raw.setdefault("metadata", {})["source_file"] = str(path)
        try:
            contracts.append(AgentContract.from_dict(raw))
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(f"Invalid contract YAML '{path}': {exc}") from exc
    return contracts


def load_named_config(config_dir: str | Path, name: str, default=None):
    path = Path(config_dir) / name
    return load_yaml(path) if path.exists() else default
