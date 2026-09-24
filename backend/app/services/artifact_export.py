from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable

from app.models.core import Artifact


EXPORTABLE_ARTIFACT_TYPES = frozenset({"declaration", "personnel_collection"})


def exportable_artifacts(artifacts: Iterable[Artifact]) -> list[Artifact]:
    return [
        artifact
        for artifact in artifacts
        if artifact.artifact_type in EXPORTABLE_ARTIFACT_TYPES and Path(artifact.stored_path).is_file()
    ]


def safe_artifact_name(file_name: str) -> str:
    return Path(file_name).name or "申报文件"


def available_destination(directory: Path, file_name: str) -> Path:
    base = safe_artifact_name(file_name)
    candidate = directory / base
    stem, suffix = candidate.stem, candidate.suffix
    index = 1
    while candidate.exists():
        candidate = directory / f"{stem} ({index}){suffix}"
        index += 1
    return candidate


def save_artifacts(artifacts: Iterable[Artifact], directory: Path) -> list[str]:
    saved: list[str] = []
    for artifact in exportable_artifacts(artifacts):
        destination = available_destination(directory, artifact.file_name)
        shutil.copy2(artifact.stored_path, destination)
        saved.append(str(destination))
    return saved


def writable_directory(directory: Path) -> bool:
    return directory.is_dir() and os.access(directory, os.W_OK)
