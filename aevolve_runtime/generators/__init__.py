"""Candidate patch generator adapters."""

from .agent_bridge import write_agent_prompts
from .base import GeneratedPatch, PatchGenerator, write_generated_patches
from .openai_compatible import OpenAICompatibleGenerator

__all__ = [
    "GeneratedPatch",
    "OpenAICompatibleGenerator",
    "PatchGenerator",
    "write_agent_prompts",
    "write_generated_patches",
]
