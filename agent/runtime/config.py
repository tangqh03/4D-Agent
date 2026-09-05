"""Strict YAML + dotenv configuration for the S2.8 agent runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values


def _keys(data: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"Unknown {where} fields: {', '.join(unknown)}")


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be a mapping")
    return value


def _required(data: dict[str, Any], name: str, where: str) -> Any:
    value = data.get(name)
    if value is None or value == "":
        raise ValueError(f"Missing {where}.{name}")
    return value


def _path(base: Path, value: Any, where: str) -> Path:
    raw = Path(str(value)).expanduser()
    return (base / raw).resolve() if not raw.is_absolute() else raw.resolve()


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api: str
    base_url_env: str
    api_key_env: str
    headers_env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    id: str
    name: str
    reasoning: bool
    thinking_level: str
    context_window: int
    max_tokens: int


@dataclass(frozen=True)
class RuntimeOptions:
    backend: str
    tool_bundle: str
    seed_skill: Path
    timeout_s: int
    max_attempts: int
    retry_backoff_s: int
    workers: int
    pi_binary: Path
    tool_python: Path
    path_prepend: tuple[Path, ...]


@dataclass(frozen=True)
class PerceptionConfig:
    mode: str
    endpoint_env: str
    python: Path
    script: Path
    model_path: Path
    visible_devices: str
    eager: bool
    startup_timeout_s: int


@dataclass(frozen=True)
class DatasetConfig:
    adapter: str
    root: Path
    split_config: Path


@dataclass(frozen=True)
class ArtifactConfig:
    trajectory_root: Path


@dataclass(frozen=True)
class AgentConfig:
    """Resolved configuration. Secret values are excluded from repr/serialization."""

    source: Path
    env_file: Path
    providers: dict[str, ProviderConfig]
    policy: ModelConfig
    observer: ModelConfig
    agent: RuntimeOptions
    perception: PerceptionConfig
    dataset: DatasetConfig
    artifacts: ArtifactConfig
    env_values: dict[str, str] = field(repr=False, compare=False)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AgentConfig":
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Agent config not found: {source}")
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        raw = _mapping(raw, "config")
        _keys(raw, {"version", "env_file", "providers", "models", "agent",
                    "perception", "dataset", "artifacts"}, "config")
        if raw.get("version") != 1:
            raise ValueError("config.version must be 1")
        base = source.parent

        env_file = _path(base, _required(raw, "env_file", "config"), "env_file")
        if not env_file.is_file():
            raise FileNotFoundError(f"dotenv file not found: {env_file}")
        parsed_env = dotenv_values(env_file)
        env_values = {str(k): str(v) for k, v in parsed_env.items() if v is not None}

        providers_raw = _mapping(_required(raw, "providers", "config"), "providers")
        providers: dict[str, ProviderConfig] = {}
        for name, value in providers_raw.items():
            item = _mapping(value, f"providers.{name}")
            _keys(item, {"api", "base_url_env", "api_key_env", "headers_env"},
                  f"providers.{name}")
            api = str(item.get("api", "openai-completions"))
            if api != "openai-completions":
                raise ValueError(f"providers.{name}.api must be openai-completions")
            headers = item.get("headers_env", {})
            headers = _mapping(headers, f"providers.{name}.headers_env")
            providers[str(name)] = ProviderConfig(
                name=str(name), api=api,
                base_url_env=str(_required(item, "base_url_env", f"providers.{name}")),
                api_key_env=str(_required(item, "api_key_env", f"providers.{name}")),
                headers_env={str(k): str(v) for k, v in headers.items()},
            )
        if not providers:
            raise ValueError("At least one provider is required")

        models = _mapping(_required(raw, "models", "config"), "models")
        _keys(models, {"policy", "observer"}, "models")
        policy = cls._parse_model(_mapping(_required(models, "policy", "models"),
                                          "models.policy"), "models.policy", providers)
        observer_raw = _mapping(models.get("observer", {"inherit": "policy"}),
                                "models.observer")
        if observer_raw.get("inherit") == "policy":
            _keys(observer_raw, {"inherit"}, "models.observer")
            observer = policy
        else:
            observer = cls._parse_model(observer_raw, "models.observer", providers)

        agent_raw = _mapping(_required(raw, "agent", "config"), "agent")
        _keys(agent_raw, {"backend", "tool_bundle", "seed_skill", "timeout_s",
                          "max_attempts", "retry_backoff_s", "workers", "pi_binary",
                          "tool_python", "path_prepend"}, "agent")
        agent = RuntimeOptions(
            backend=str(agent_raw.get("backend", "pi")),
            tool_bundle=str(agent_raw.get("tool_bundle", "s2_8_observation")),
            seed_skill=_path(base, _required(agent_raw, "seed_skill", "agent"), "agent.seed_skill"),
            timeout_s=int(agent_raw.get("timeout_s", 600)),
            max_attempts=int(agent_raw.get("max_attempts", 3)),
            retry_backoff_s=int(agent_raw.get("retry_backoff_s", 5)),
            workers=int(agent_raw.get("workers", 1)),
            pi_binary=_path(base, _required(agent_raw, "pi_binary", "agent"), "agent.pi_binary"),
            tool_python=_path(base, _required(agent_raw, "tool_python", "agent"), "agent.tool_python"),
            path_prepend=tuple(_path(base, p, "agent.path_prepend")
                               for p in agent_raw.get("path_prepend", [])),
        )
        if agent.backend != "pi" or agent.tool_bundle != "s2_8_observation":
            raise ValueError("v1 supports only backend=pi and tool_bundle=s2_8_observation")
        if min(agent.timeout_s, agent.max_attempts, agent.workers) < 1:
            raise ValueError("agent timeout_s, max_attempts, and workers must be positive")

        perception_raw = _mapping(_required(raw, "perception", "config"), "perception")
        _keys(perception_raw, {"mode", "endpoint_env", "python", "script", "model_path",
                               "visible_devices", "eager", "startup_timeout_s"}, "perception")
        perception = PerceptionConfig(
            mode=str(perception_raw.get("mode", "managed")),
            endpoint_env=str(_required(perception_raw, "endpoint_env", "perception")),
            python=_path(base, _required(perception_raw, "python", "perception"), "perception.python"),
            script=_path(base, _required(perception_raw, "script", "perception"), "perception.script"),
            model_path=_path(base, _required(perception_raw, "model_path", "perception"), "perception.model_path"),
            visible_devices=str(perception_raw.get("visible_devices", "")),
            eager=bool(perception_raw.get("eager", True)),
            startup_timeout_s=int(perception_raw.get("startup_timeout_s", 180)),
        )
        if perception.mode != "managed":
            raise ValueError("v1 supports only perception.mode=managed")

        dataset_raw = _mapping(_required(raw, "dataset", "config"), "dataset")
        _keys(dataset_raw, {"adapter", "root", "split_config"}, "dataset")
        dataset = DatasetConfig(
            adapter=str(dataset_raw.get("adapter", "vistr")),
            root=_path(base, _required(dataset_raw, "root", "dataset"), "dataset.root"),
            split_config=_path(base, _required(dataset_raw, "split_config", "dataset"), "dataset.split_config"),
        )
        if dataset.adapter != "vistr":
            raise ValueError("v1 ships only the vistr dataset adapter")

        artifacts_raw = _mapping(_required(raw, "artifacts", "config"), "artifacts")
        _keys(artifacts_raw, {"trajectory_root"}, "artifacts")
        artifacts = ArtifactConfig(
            trajectory_root=_path(base, _required(artifacts_raw, "trajectory_root", "artifacts"),
                                  "artifacts.trajectory_root"))

        config = cls(source=source, env_file=env_file, providers=providers,
                     policy=policy, observer=observer, agent=agent,
                     perception=perception, dataset=dataset, artifacts=artifacts,
                     env_values=env_values)
        config.validate()
        return config

    @staticmethod
    def _parse_model(raw: dict[str, Any], where: str,
                     providers: dict[str, ProviderConfig]) -> ModelConfig:
        _keys(raw, {"provider", "id", "name", "reasoning", "thinking_level",
                    "context_window", "max_tokens"}, where)
        provider = str(_required(raw, "provider", where))
        if provider not in providers:
            raise ValueError(f"{where}.provider references unknown provider: {provider}")
        model_id = str(_required(raw, "id", where))
        context_window = int(raw.get("context_window", -1))
        max_tokens = int(raw.get("max_tokens", -1))
        if context_window != -1 and context_window < 1:
            raise ValueError(f"{where}.context_window must be -1 or positive")
        if max_tokens != -1 and max_tokens < 1:
            raise ValueError(f"{where}.max_tokens must be -1 or positive")
        thinking_level = str(raw.get("thinking_level", "")).strip().lower()
        allowed_levels = {"", "off", "minimal", "low", "medium", "high", "xhigh", "max"}
        if thinking_level not in allowed_levels:
            raise ValueError(f"{where}.thinking_level is invalid: {thinking_level!r}")
        if thinking_level and not bool(raw.get("reasoning", False)):
            raise ValueError(f"{where}.thinking_level requires reasoning=true")
        return ModelConfig(
            provider=provider, id=model_id, name=str(raw.get("name", model_id)),
            reasoning=bool(raw.get("reasoning", False)),
            thinking_level=thinking_level,
            context_window=context_window, max_tokens=max_tokens)

    def validate(self) -> None:
        required_files = [self.agent.seed_skill, self.agent.pi_binary,
                          self.agent.tool_python, self.perception.python,
                          self.perception.script]
        missing = [str(p) for p in required_files if not p.is_file()]
        if missing:
            raise FileNotFoundError("Required files not found: " + ", ".join(missing))
        required_dirs = [self.dataset.root, self.perception.model_path, *self.agent.path_prepend]
        missing_dirs = [str(p) for p in required_dirs if not p.is_dir()]
        if missing_dirs:
            raise FileNotFoundError("Required directories not found: " + ", ".join(missing_dirs))
        if not self.dataset.split_config.is_file():
            raise FileNotFoundError(f"Split config not found: {self.dataset.split_config}")
        names: set[str] = {self.perception.endpoint_env}
        for model in (self.policy, self.observer):
            provider = self.providers[model.provider]
            names.update([provider.base_url_env, provider.api_key_env])
            names.update(provider.headers_env.values())
        missing_env = sorted(name for name in names if not self.env_values.get(name))
        if missing_env:
            raise ValueError("Missing non-empty dotenv values: " + ", ".join(missing_env))

    def child_env(self, parent: dict[str, str] | None = None) -> dict[str, str]:
        import os
        env = dict(os.environ if parent is None else parent)
        env.update(self.env_values)
        path = env.get("PATH", "")
        if self.agent.path_prepend:
            env["PATH"] = ":".join([*(str(p) for p in self.agent.path_prepend), path])
        return env

    def public_dict(self) -> dict[str, Any]:
        """Secret-free resolved config used for hashing and manifests."""
        value = asdict(self)
        value.pop("env_values", None)
        return _json_paths(value)


def _json_paths(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_paths(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_paths(v) for v in value]
    return value
