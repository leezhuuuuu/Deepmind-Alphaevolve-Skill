"""OpenAI-compatible chat completion patch generator."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request

from .base import GeneratedPatch, PatchGenerator
from aevolve_runtime.prompt_sampler import build_mutation_prompt
from aevolve_runtime.task_spec import GenerationApiConfig, TaskSpec


class OpenAICompatibleGenerator(PatchGenerator):
    """Generate SEARCH/REPLACE patches through an OpenAI-compatible endpoint."""

    def generate(self, task: TaskSpec, *, count: int) -> list[GeneratedPatch]:
        if count <= 0:
            return []
        api = task.generation.api
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
        coerced = _coerce_code_to_replace_patch(stripped, task)
        return coerced or stripped

    start = first_search
    if first_search > 0 and lines[first_search - 1].strip().startswith("FILE: "):
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


def _split_file_payload(content: str, task: TaskSpec) -> tuple[str, str]:
    default_file = task.target.files[0]
    lines = content.splitlines()
    if lines and lines[0].strip().startswith("FILE: "):
        file_name = lines[0].split(":", 1)[1].strip()
        if file_name in task.target.files:
            return file_name, "\n".join(lines[1:]).strip()
    return default_file, content


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
