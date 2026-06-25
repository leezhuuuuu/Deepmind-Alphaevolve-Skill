"""OpenAI-compatible chat completion patch generator."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, parse, request

from .base import GeneratedPatch, PatchGenerator
from aevolve_runtime.prompt_sampler import build_mutation_prompt
from aevolve_runtime.task_spec import GenerationApiConfig, TaskSpec


class OpenAICompatibleGenerator(PatchGenerator):
    """Generate SEARCH/REPLACE patches through an OpenAI-compatible endpoint."""

    def __init__(self, *, allow_custom_api_base: bool = False, allowed_api_key_envs: set[str] | None = None):
        self.allow_custom_api_base = allow_custom_api_base
        self.allowed_api_key_envs = allowed_api_key_envs or set()

    def generate(self, task: TaskSpec, *, count: int) -> list[GeneratedPatch]:
        if count <= 0:
            return []
        api = task.generation.api
        _validate_api_target(
            api,
            allow_custom_api_base=self.allow_custom_api_base,
            extra_allowed_envs=self.allowed_api_key_envs,
        )
        api_key = os.environ.get(api.api_key_env)
        if not api_key:
            raise RuntimeError(f"missing API key environment variable: {api.api_key_env}")

        patches: list[GeneratedPatch] = []
        for index in range(1, count + 1):
            feedback = _diversity_hint(index, count)
            bundle = build_mutation_prompt(task, candidate_index=index, prior_feedback=feedback)
            response = _chat_completion(api=api, api_key=api_key, messages=bundle.messages())
            content = _extract_message_content(response)
            patches.append(
                GeneratedPatch(
                    patch_text=_extract_patch_text(content, task),
                    source=f"{api.provider}:{api.model}",
                    metadata={
                        "candidate_index": str(index),
                        "prompt_hash": bundle.prompt_hash,
                        "provider": api.provider,
                        "model": api.model,
                    },
                )
            )
        return patches


def _chat_completion(api: GenerationApiConfig, api_key: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": api.model,
        "messages": messages,
        "temperature": api.temperature,
        "max_tokens": api.max_tokens,
        "stream": False,
    }
    if api.provider.lower() == "deepseek":
        payload["thinking"] = {"type": api.thinking}
        if api.reasoning_effort:
            payload["reasoning_effort"] = api.reasoning_effort

    body = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        f"{api.base_url}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with request.urlopen(http_request, timeout=api.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM API request failed: HTTP {exc.code}: {_redact(details, api_key)}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"LLM API request failed: {_redact(str(exc), api_key)}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("LLM API returned invalid JSON") from exc


def _validate_api_target(
    api: GenerationApiConfig,
    *,
    allow_custom_api_base: bool,
    extra_allowed_envs: set[str],
) -> None:
    parsed = parse.urlparse(api.base_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise RuntimeError("generation.api.base_url must be an HTTP(S) URL with a hostname")
    loopback = _is_loopback_host(host)
    if parsed.scheme == "http" and not loopback:
        raise RuntimeError("generation.api.base_url may use http only for loopback endpoints")

    provider = api.provider.lower()
    allowed_hosts = _known_provider_hosts().get(provider, set())
    if not loopback and host not in allowed_hosts and not allow_custom_api_base:
        allowed = ", ".join(sorted(allowed_hosts)) or "loopback endpoints"
        raise RuntimeError(
            f"generation.api.base_url host {host!r} is not trusted for provider {api.provider!r}; "
            f"expected {allowed} or pass --allow-custom-api-base"
        )

    if not loopback and not _is_allowed_api_key_env(api, extra_allowed_envs):
        raise RuntimeError(
            f"generation.api.api_key_env {api.api_key_env!r} is not allowed for external API calls; "
            "use the provider default, an AEVOLVE_*_API_KEY variable, or pass --allow-api-key-env"
        )


def _known_provider_hosts() -> dict[str, set[str]]:
    return {
        "anthropic": {"api.anthropic.com"},
        "deepseek": {"api.deepseek.com"},
        "openai": {"api.openai.com"},
    }


def _is_allowed_api_key_env(api: GenerationApiConfig, extra_allowed_envs: set[str]) -> bool:
    if api.api_key_env in extra_allowed_envs:
        return True
    provider_defaults = {
        "anthropic": {"ANTHROPIC_API_KEY"},
        "deepseek": {"DEEPSEEK_API_KEY"},
        "openai": {"OPENAI_API_KEY"},
    }
    if api.api_key_env in provider_defaults.get(api.provider.lower(), set()):
        return True
    return api.api_key_env.startswith("AEVOLVE_") and api.api_key_env.endswith("_API_KEY")


def _is_loopback_host(host: str) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"}


def _extract_message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("LLM API response has no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise RuntimeError("LLM API response choice has no message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("LLM API response message has empty content")
    return content


def _extract_patch_text(content: str, task: TaskSpec) -> str:
    stripped = _strip_fence(content.strip())
    lines = stripped.splitlines()
    first_search = None
    last_replace = None
    for index, line in enumerate(lines):
        if line.strip() == "<<<<<<< SEARCH" and first_search is None:
            first_search = index
        if line.strip() == ">>>>>>> REPLACE":
            last_replace = index
    if first_search is None or last_replace is None or last_replace < first_search:
        labeled = _coerce_labeled_search_replace(stripped, task)
        if labeled:
            return labeled
        coerced = _coerce_code_to_replace_patch(stripped, task)
        return coerced or stripped

    start = first_search
    if first_search > 0 and _file_marker(lines[first_search - 1]):
        start = first_search - 1
    return "\n".join(lines[start : last_replace + 1]).strip()


def _strip_fence(content: str) -> str:
    if not content.startswith("```"):
        return content
    lines = content.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return content


def _coerce_code_to_replace_patch(content: str, task: TaskSpec) -> str | None:
    file_name, payload = _split_file_payload(content, task)
    code = _extract_code_payload(payload)
    if not _looks_like_code(code):
        return None
    current = (task.root / file_name).read_text(encoding="utf-8")
    return (
        f"FILE: {file_name}\n"
        "<<<<<<< SEARCH\n"
        f"{_ensure_trailing_newline(current)}"
        "=======\n"
        f"{_ensure_trailing_newline(code)}"
        ">>>>>>> REPLACE"
    )


def _coerce_labeled_search_replace(content: str, task: TaskSpec) -> str | None:
    file_name, payload = _split_file_payload(content, task)
    payload = _extract_code_payload(payload)
    lines = payload.splitlines(keepends=True)
    search_index = None
    replace_index = None
    for index, line in enumerate(lines):
        label = line.strip().rstrip(":").upper()
        if label == "SEARCH" and search_index is None:
            search_index = index
        elif label == "REPLACE" and search_index is not None:
            replace_index = index
            break
    if search_index is None or replace_index is None:
        return None
    search = "".join(lines[search_index + 1 : replace_index])
    replace = "".join(lines[replace_index + 1 :])
    if not search.strip() or not replace.strip():
        return None
    return (
        f"FILE: {file_name}\n"
        "<<<<<<< SEARCH\n"
        f"{_ensure_trailing_newline(search)}"
        "=======\n"
        f"{_ensure_trailing_newline(replace)}"
        ">>>>>>> REPLACE"
    )


def _split_file_payload(content: str, task: TaskSpec) -> tuple[str, str]:
    default_file = task.target.files[0]
    lines = content.splitlines()
    if lines and (file_name := _file_marker(lines[0])):
        if file_name in task.target.files:
            return file_name, "\n".join(lines[1:]).strip()
    return default_file, content


def _file_marker(line: str) -> str | None:
    stripped = line.strip()
    prefixes = ["FILE:", "### FILE:", "*** File:"]
    for prefix in prefixes:
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip() or None
    return None


def _extract_code_payload(content: str) -> str:
    lines = content.strip().splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith("```"):
            body: list[str] = []
            for inner in lines[index + 1 :]:
                if inner.strip() == "```":
                    return "\n".join(body).strip()
                body.append(inner)
    return content.strip()


def _looks_like_code(content: str) -> bool:
    return "def " in content or "# EVOLVE-BLOCK-START" in content or "class " in content


def _ensure_trailing_newline(content: str) -> str:
    return content if content.endswith("\n") else f"{content}\n"


def _diversity_hint(index: int, count: int) -> str:
    if count == 1:
        return "Focus on the highest-confidence improvement you can make."
    strategies = [
        "Try a conservative local improvement that preserves behavior.",
        "Try a different algorithmic strategy than a simple local tweak.",
        "Try improving edge cases or robustness while keeping the patch small.",
        "Try reducing work on common cases without changing the interface.",
    ]
    return strategies[(index - 1) % len(strategies)]


def _redact(value: str, secret: str) -> str:
    if not secret:
        return value
    return value.replace(secret, "[redacted]")
