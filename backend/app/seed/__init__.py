"""Deterministic seed corpus — docs/12."""

from __future__ import annotations

from app.seed.generator import EPOCH, SEED, SEED_VERSION, Corpus, generate
from app.seed.writer import clear, write

__all__ = ["EPOCH", "SEED", "SEED_VERSION", "Corpus", "clear", "generate", "write"]
