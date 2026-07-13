"""Generic, domain-blind built-in adapters."""
import asyncio
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
import importlib
import inspect
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base_adapter import BaseAgentAdapter
from .redaction import safe_summary
from .tracing import get_tracer
from .exceptions import (
    AdapterError,
    AdapterConfigurationError,
    AdapterConnectionError,
    AdapterInvocationError,
    AdapterResponseError,
    AdapterTimeoutError,
)


def resolve_entrypoint(path):
    try:
        module, name = path.rsplit(".", 1)
        return getattr(importlib.import_module(module), name)
    except Exception as exc:
        raise AdapterConfigurationError(f"Unable to resolve adapter entrypoint '{path}': {exc}") from exc


class PythonFunctionAgentAdapter(BaseAgentAdapter):
    def __init__(self, manifest, services=None):
        super().__init__(manifest, services)
        self.target = resolve_entrypoint(manifest.entrypoint)

    @property
    def timeout_seconds(self):
        return float(self.manifest.metadata.get("timeout_seconds", 30))

    def _invoke_target(self, payload, trace_id):
        try:
            with get_tracer().span("python_function_call", inputs=safe_summary(payload), metadata={"entrypoint": self.manifest.entrypoint, "trace_id": trace_id}, run_type="tool") as span:
                result = self.target(payload, trace_id=trace_id)
                if inspect.isawaitable(result):
                    raise AdapterInvocationError("Asynchronous entrypoint must be called through invoke_async")
                normalized = result if isinstance(result, dict) else {"result": result}
                span.set_output(normalized)
                return normalized
        except AdapterInvocationError:
            raise
        except Exception as exc:
            raise AdapterInvocationError(f"Agent entrypoint failed: {exc}") from exc

    def invoke(self, payload, trace_id):
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-adapter")
        context = copy_context()
        future = executor.submit(context.run, self._invoke_target, payload, trace_id)
        try:
            return future.result(timeout=self.timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise AdapterTimeoutError(f"Agent invocation exceeded {self.timeout_seconds:g} seconds") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    async def invoke_async(self, payload, trace_id):
        try:
            if inspect.iscoroutinefunction(self.target):
                with get_tracer().span("python_function_call", inputs=safe_summary(payload), metadata={"entrypoint": self.manifest.entrypoint, "trace_id": trace_id}, run_type="tool") as span:
                    result = await asyncio.wait_for(self.target(payload, trace_id=trace_id), timeout=self.timeout_seconds)
                    normalized = result if isinstance(result, dict) else {"result": result}
                    span.set_output(normalized)
                    return normalized
            return await asyncio.wait_for(asyncio.to_thread(self._invoke_target, payload, trace_id), timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise AdapterTimeoutError(f"Agent invocation exceeded {self.timeout_seconds:g} seconds") from exc
        except AdapterInvocationError:
            raise
        except Exception as exc:
            raise AdapterInvocationError(f"Agent entrypoint failed: {exc}") from exc


class LangGraphAgentAdapter(PythonFunctionAgentAdapter):
    def _graph_target(self):
        return self.target() if inspect.isclass(self.target) else self.target

    def _invoke_target(self, payload, trace_id):
        try:
            target = self._graph_target()
            result = target.invoke(payload, config={"configurable": {"thread_id": trace_id}}) if hasattr(target, "invoke") else target(payload, trace_id=trace_id)
            return result if isinstance(result, dict) else {"result": result}
        except Exception as exc:
            raise AdapterInvocationError(f"Graph invocation failed: {exc}") from exc

    async def invoke_async(self, payload, trace_id):
        target = self._graph_target()
        try:
            if hasattr(target, "ainvoke"):
                return await asyncio.wait_for(target.ainvoke(payload, config={"configurable": {"thread_id": trace_id}}), timeout=self.timeout_seconds)
            return await asyncio.wait_for(asyncio.to_thread(self._invoke_target, payload, trace_id), timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise AdapterTimeoutError(f"Graph invocation exceeded {self.timeout_seconds:g} seconds") from exc
        except AdapterInvocationError:
            raise
        except Exception as exc:
            raise AdapterInvocationError(f"Graph invocation failed: {exc}") from exc


class RestApiAgentAdapter(BaseAgentAdapter):
    def _headers(self):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        env_name = self.manifest.metadata.get("auth_env_var")
        if env_name:
            token = os.environ.get(env_name)
            if not token:
                raise AdapterConfigurationError(f"Required authentication environment variable '{env_name}' is not set")
            headers["Authorization"] = f"Bearer {token}"
        return headers

    @property
    def timeout_seconds(self):
        return float(self.manifest.metadata.get("timeout_seconds", 30))

    @property
    def max_attempts(self):
        return max(1, int(self.manifest.metadata.get("retry", {}).get("max_attempts", 1)))

    def _request(self, endpoint, payload, method="POST", expect_json=True):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(endpoint, data=body, headers=self._headers(), method=method)
        try:
            with get_tracer().span("rest_api_call", inputs={"method": method, "endpoint": endpoint, "payload": safe_summary(payload)}, metadata={"adapter_type": self.manifest.adapter_type}, run_type="tool") as span:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    result = {} if not raw else json.loads(raw) if expect_json else {"reachable": True}
                    span.set_output({"status_code": response.status, "response": safe_summary(result)})
                    return result
        except HTTPError as exc:
            raise AdapterResponseError(f"External agent returned HTTP {exc.code}") from exc
        except (URLError, ConnectionError, OSError) as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError) or isinstance(exc, TimeoutError):
                raise AdapterTimeoutError(f"External agent timed out after {self.timeout_seconds:g} seconds") from exc
            raise AdapterConnectionError(f"External agent is unreachable: {getattr(exc, 'reason', exc)}") from exc
        except json.JSONDecodeError as exc:
            raise AdapterResponseError("External agent returned invalid JSON") from exc

    def invoke(self, payload, trace_id):
        last_error = None
        for _attempt in range(1, self.max_attempts + 1):
            try:
                return self._request(self.manifest.endpoint, {**payload, "trace_id": trace_id})
            except (AdapterConnectionError, AdapterTimeoutError) as exc:
                last_error = exc
        raise last_error or AdapterInvocationError("External agent invocation failed")

    async def invoke_async(self, payload, trace_id):
        return await asyncio.to_thread(self.invoke, payload, trace_id)

    def get_health(self):
        health = self.manifest.metadata.get("health_check", {})
        endpoint = health.get("endpoint")
        if not endpoint:
            return super().get_health()
        try:
            self._request(endpoint, None, method="GET", expect_json=False)
            status, details = "healthy", {"endpoint": endpoint, "reachable": True}
        except AdapterError as exc:
            status, details = "unreachable", {"endpoint": endpoint, "reachable": False, "reason": str(exc)}
        return {"status": status, "agent_id": self.manifest.agent_id, "last_checked": datetime.now(timezone.utc).isoformat(), "details": details}


class ExternalWebhookAgentAdapter(RestApiAgentAdapter):
    def invoke(self, payload, trace_id):
        return {"accepted": True, "delivery": super().invoke(payload, trace_id), "trace_id": trace_id}

    def get_health(self):
        health = self.manifest.metadata.get("health_check", {})
        max_age = health.get("max_heartbeat_age_seconds")
        store = getattr(self.services, "store", None) if self.services else None
        if max_age is None or store is None:
            return BaseAgentAdapter.get_health(self)
        rows = store.query(
            "SELECT timestamp FROM observability_events WHERE agent_id=? AND event_type='HEARTBEAT' ORDER BY id DESC LIMIT 1",
            (self.manifest.agent_id,),
        )
        now = datetime.now(timezone.utc)
        if not rows:
            return {"status": "unknown", "agent_id": self.manifest.agent_id, "last_checked": now.isoformat(), "details": {"reason": "No heartbeat recorded"}}
        heartbeat = datetime.fromisoformat(rows[0]["timestamp"].replace("Z", "+00:00"))
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        age = (now - heartbeat).total_seconds()
        return {
            "status": "healthy" if age <= float(max_age) else "stale",
            "agent_id": self.manifest.agent_id,
            "last_checked": now.isoformat(),
            "details": {"last_heartbeat": heartbeat.isoformat(), "age_seconds": round(age, 1), "max_age_seconds": float(max_age)},
        }


class A2AAgentAdapter(RestApiAgentAdapter):
    """Outbound A2A client adapter for external agents.

    It lets the harness govern external A2A agents through the same contract,
    RBAC, lifecycle, budget, audit, and observability controls as internal
    agents. The external endpoint is expected to accept the JSON-RPC A2A
    `message/send` method.
    """

    def invoke(self, payload, trace_id):
        message_text = payload.get("query") or payload.get("message") or payload.get("task") or json.dumps(payload, default=str)
        task_id = payload.get("task_id") or trace_id
        context_id = payload.get("session_id") or payload.get("context_id") or trace_id
        rpc_payload = {
            "jsonrpc": "2.0",
            "id": trace_id,
            "method": "message/send",
            "params": {
                "agent_id": self.manifest.metadata.get("remote_agent_id") or self.manifest.agent_id,
                "context_id": context_id,
                "message": {
                    "role": "user",
                    "task_id": task_id,
                    "context_id": context_id,
                    "parts": [{"type": "text", "text": message_text}],
                    "metadata": {"payload": payload},
                },
                "metadata": {"trace_id": trace_id, "source": "agent_harness_a2a_adapter"},
            },
        }
        response = self._request(self.manifest.endpoint, rpc_payload)
        if "error" in response:
            raise AdapterResponseError(f"A2A agent returned error: {response['error']}")
        result = response.get("result", response)
        return {"a2a_task": result, "result": result}
