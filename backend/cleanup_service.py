# -*- coding: utf-8 -*-
"""Clean generated local carriers without deleting input reports."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict


GENERATED_DIRECTORY_NAMES = ("artifacts",)


def _validated_generated_directory(project_root: Path, directory_name: str) -> Path:
    """Restrict deletion to allowlisted generated directories under the project root."""
    root = Path(project_root).resolve()
    if directory_name not in GENERATED_DIRECTORY_NAMES:
        raise RuntimeError(f"拒绝清理非白名单目录：{directory_name}")
    target = (root / directory_name).resolve()
    if target == root or root not in target.parents:
        raise RuntimeError(f"拒绝清理项目范围外的目录：{target}")
    return target


def _clear_directories(project_root: Path, directory_names: tuple[str, ...]) -> Dict[str, int]:
    """Empty the specified generated directories and recreate them."""
    deleted_files = 0
    deleted_bytes = 0
    deleted_directories = 0

    for directory_name in directory_names:
        target = _validated_generated_directory(project_root, directory_name)
        if target.exists():
            files = [item for item in target.rglob("*") if item.is_file()]
            directories = [item for item in target.rglob("*") if item.is_dir()]
            deleted_files += len(files)
            deleted_bytes += sum(item.stat().st_size for item in files)
            deleted_directories += len(directories)
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

    return {
        "deleted_files": deleted_files,
        "deleted_bytes": deleted_bytes,
        "deleted_directories": deleted_directories,
    }


def clear_local_extracted_artifacts(project_root: Path) -> Dict[str, int]:
    """Clear only extracted tables and images under artifacts."""
    return _clear_directories(project_root, ("artifacts",))


