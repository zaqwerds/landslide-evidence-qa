"""Core package for landslide knowledge graphs and evidence-based QA."""

import sys
from pathlib import Path


_program_dir = str(Path(__file__).resolve().parent)
if _program_dir not in sys.path:
    sys.path.insert(0, _program_dir)

from backend.pipeline import CorePipeline, PipelineConfig

__all__ = ["CorePipeline", "PipelineConfig"]
