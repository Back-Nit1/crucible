"""Runtime QwenInferenceClient over the Modal server (agents.model.QwenInferenceClient implementation).

Security/reliability properties (all tested with an injected transport; no network, no GPU in tests):
  * pinned model + revision, checked on the request AND on every response; mismatch fails closed;
  * the GPU cannot be reached without explicit launch authorization (rotated token, billing, approved cost ceiling);
  * spend is capped by the approved ceiling; unknown cost is reported as unknown, never as free;
  * bounded timeout with cancellation; every failure is a structured InferenceError carrying no message text from
    the transport (which could contain URLs or credentials);
  * nothing is ever executed from model output; the client returns raw text for agents.model to parse and validate;
  * no fallback: any failure raises, the caller never receives a substituted answer."""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from decimal import Decimal
from typing import Protocol

from pydantic import ValidationError

from agents.model import InferenceError, ModelRequest, QwenInferenceResponse
from modal_app.adapter_artifact import AdapterSelection
from modal_app.qwen_protocol import MAX_NEW_TOKENS_CEILING, QwenRejection, QwenRequest, QwenResult
from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION, estimate_modal_cost

PROBE_CEILING_USD = Decimal("0.861948")  # the previously approved 45-minute L4 ceiling; never raised in code
LAUNCH_FLAGS = ("CRUCIBLE_MODAL_TOKEN_ROTATED", "CRUCIBLE_MODAL_BILLING_CONFIRMED")
CEILING_VAR = "CRUCIBLE_MODAL_APPROVED_CEILING_USD"


class Transport(Protocol):
    def __call__(self, payload: dict, timeout: float) -> dict: ...
    # optional: def cancel(self) -> None


def require_launch_authorization(env: Mapping[str, str] | None = None) -> Decimal:
    """Return the user-approved spend ceiling, or raise naming exactly which confirmations are missing.
    The user sets these after rotating the token, adding billing and approving the ceiling; code never sets them."""
    env = os.environ if env is None else env
    missing = [name for name in LAUNCH_FLAGS if env.get(name) != "1"]
    try:
        ceiling = Decimal(env.get(CEILING_VAR, ""))
    except Exception:
        ceiling = Decimal(0)
    if ceiling <= 0:
        missing.append(CEILING_VAR)
    if missing:
        raise InferenceError("gpu_launch_not_authorized", "missing confirmations: " + ", ".join(missing))
    return ceiling


def modal_transport(app_name: str = "crucible-qwen-inference", cls_name: str = "Qwen") -> Transport:
    """Real transport. Requires an already-deployed server; importing/constructing it never starts a GPU by itself."""
    import modal
    method = modal.Cls.from_name(app_name, cls_name)().generate

    class _Transport:
        call = None

        def __call__(self, payload: dict, timeout: float) -> dict:
            self.call = method.spawn(payload)
            return self.call.get(timeout=timeout)

        def cancel(self) -> None:
            if self.call is not None:
                self.call.cancel()
    return _Transport()


def qwen_tools(tools) -> list[dict[str, object]]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in tools]


def to_qwen_messages(messages) -> list[dict[str, object]]:
    """Runtime Message history -> Qwen chat messages. The trainer renders its data through this same function, so
    what the adapter is trained on is byte-for-byte the format the inference client sends."""
    out: list[dict[str, object]] = []
    for m in messages:
        if m.role == "tool":
            out.append({"role": "tool", "content": json.dumps(m.tool_result, sort_keys=True, default=str)})
        elif m.tool_name:
            out.append({"role": "assistant", "content": "", "tool_calls": [
                {"type": "function", "function": {"name": m.tool_name, "arguments": m.tool_arguments or {}}}]})
        else:
            out.append({"role": m.role, "content": m.content})
    return out


class ModalQwenClient:
    def __init__(self, transport: Transport, *, cost_ceiling: Decimal, timeout_seconds: float = 120.0,
                 max_new_tokens: int = 256, checkpoint_label: str | None = None, grace_seconds: float = 5.0,
                 adapter: AdapterSelection | None = None):
        """`adapter` pins this client to ONE trained checkpoint: every request carries its identity, the server must
        answer with the same identity, and anything else fails closed. Without it the client serves the pinned base."""
        if not 0 < max_new_tokens <= MAX_NEW_TOKENS_CEILING or timeout_seconds <= 0 or cost_ceiling <= 0:
            raise ValueError("max_new_tokens, timeout and cost ceiling must be positive and bounded")
        self.transport, self.cost_ceiling, self.adapter = transport, cost_ceiling, adapter
        checkpoint_label = checkpoint_label or (adapter.checkpoint_id if adapter else "qwen-base")
        if adapter and checkpoint_label != adapter.checkpoint_id:
            raise ValueError("an adapter client's checkpoint label is its adapter checkpoint id")
        self.timeout_seconds, self.max_new_tokens, self.checkpoint_label = timeout_seconds, max_new_tokens, checkpoint_label
        self.grace_seconds = grace_seconds  # extra wait beyond the transport's own timeout before we cancel
        self.spent, self.calls = Decimal(0), 0

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None, **kwargs) -> "ModalQwenClient":
        """The only path that builds the real transport, and only after launch authorization."""
        ceiling = require_launch_authorization(env)  # first: no import of modal, no transport, without authorization
        return cls(modal_transport(), cost_ceiling=ceiling, **kwargs)

    def invoke(self, request: ModelRequest, retry: int) -> QwenInferenceResponse:
        allowed = (None, self.checkpoint_label) if self.adapter else (None, self.checkpoint_label, MODEL_REVISION)
        if request.checkpoint not in allowed:  # e.g. a base-model request on an adapter client is NOT answered from base
            raise InferenceError("checkpoint_mismatch", "request pins a checkpoint this client does not serve")
        if self.spent >= self.cost_ceiling:
            raise InferenceError("cost_ceiling_reached", f"spent {self.spent} of approved {self.cost_ceiling}")
        try:
            payload = QwenRequest(
                system=request.system_prompt, messages=to_qwen_messages(request.messages),
                tools=qwen_tools(request.tools),
                seed=((request.seed or 0) + retry) % 2**32, temperature=float(request.temperature),
                max_new_tokens=self.max_new_tokens, adapter=self.adapter).model_dump(mode="json", exclude_none=True)
        except ValidationError as exc:
            raise InferenceError("invalid_request", f"{len(exc.errors())} validation error(s)") from None
        result = self._call(payload)
        if isinstance(result, dict) and "error_code" in result:  # structured refusal from the server, before inference
            try:
                refusal = QwenRejection.model_validate(result)
            except ValidationError:
                raise InferenceError("invalid_refusal", "server refusal failed schema validation")  # a refusal: never retried from None
            raise InferenceError(refusal.error_code, refusal.detail)
        try:
            parsed = QwenResult.model_validate(result)
        except ValidationError:
            raise InferenceError("invalid_response", "server response failed schema validation") from None
        if (parsed.model, parsed.revision) != (MODEL_ID, MODEL_REVISION):
            raise InferenceError("model_identity_mismatch", "server answered with a different model or revision")
        served = (parsed.adapter_run_id, parsed.adapter_hash, parsed.training_manifest_hash)
        wanted = ((self.adapter.run_id, self.adapter.adapter_hash, self.adapter.training_manifest_hash)
                  if self.adapter else (None, None, None))
        if served != wanted:  # base answered an adapter request, an adapter answered a base one, or a different adapter
            raise InferenceError("model_identity_mismatch", "server answered with a different adapter than requested")
        seconds = parsed.generation_seconds + parsed.container_load_seconds + parsed.adapter_load_seconds
        cost = Decimal(str(estimate_modal_cost(seconds)["total_usd"]))  # list-rate estimate; Modal billing is the truth
        self.spent += cost
        self.calls += 1
        return QwenInferenceResponse(
            raw_output=parsed.raw_output, prompt_tokens=parsed.input_tokens, completion_tokens=parsed.output_tokens,
            latency_ms=round(parsed.generation_seconds * 1000), finish_reason=parsed.finish_reason, model=parsed.model,
            checkpoint=self.adapter.checkpoint_id if self.adapter else parsed.revision,
            seed_supported=parsed.seed_applied, cost=cost)

    def _call(self, payload: dict) -> dict:
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self.transport, payload, self.timeout_seconds)
        try:
            return future.result(timeout=self.timeout_seconds + self.grace_seconds)
        except (FutureTimeout, TimeoutError):
            cancel = getattr(self.transport, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:
                    pass
            raise InferenceError("timeout", f"no response within {self.timeout_seconds:.0f}s") from None
        except InferenceError:
            raise
        except Exception as exc:  # message text deliberately dropped: it may carry URLs or credentials
            raise InferenceError("transport_error", type(exc).__name__) from None
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
