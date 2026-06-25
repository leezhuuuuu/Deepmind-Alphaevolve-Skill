"""Candidate patch generator adapters."""

from .base import GeneratedPatch, PatchGenerator, write_generated_patches
from .openai_compatible import OpenAICompatibleGenerator

__all__ = ["GeneratedPatch", "OpenAICompatibleGenerator", "PatchGenerator", "write_generated_patches"]
