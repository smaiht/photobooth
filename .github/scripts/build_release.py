"""Build deterministic full and component Photobooth release archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path


COPY_CHUNK_SIZE = 1024 * 1024

COMPONENT_FOLDERS = {
    "python": "python",
    "bin": "bin",
    "templates": "templates",
    "edsdk": "EDSDK_Win",
    "drivers": "drivers",
}

ARCHIVE_NAMES = {
    "full": "photobooth-win.zip",
    "app": "photobooth-app.zip",
    "python": "photobooth-python.zip",
    "bin": "photobooth-bin.zip",
    "templates": "photobooth-templates.zip",
    "edsdk": "photobooth-edsdk.zip",
    "drivers": "photobooth-drivers.zip",
}


def _is_bytecode(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix.lower() in {".pyc", ".pyo"}


def _safe_recreate_directory(path: Path, *, forbidden: Path) -> None:
    resolved = path.resolve()
    forbidden = forbidden.resolve()
    if (resolved == forbidden
            or resolved in forbidden.parents
            or forbidden in resolved.parents):
        raise ValueError(f"refusing to recreate unsafe directory: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def _tracked_files(repo_root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    paths = []
    for raw_name in completed.stdout.split(b"\0"):
        if not raw_name:
            continue
        name = raw_name.decode("utf-8")
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe tracked release path: {name}")
        paths.append(path)
    return sorted(paths, key=lambda item: item.as_posix())


def prepare_release_stage(repo_root: Path, stage_root: Path) -> int:
    """Copy tracked files and the generated embedded runtime into a clean stage."""
    repo_root = repo_root.resolve()
    stage_root = stage_root.resolve()
    _safe_recreate_directory(stage_root, forbidden=repo_root)

    copied = 0
    for relative in _tracked_files(repo_root):
        if _is_bytecode(relative):
            continue
        source = repo_root / relative
        if not source.is_file():
            continue
        destination = stage_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1

    runtime_root = repo_root / "python"
    if not (runtime_root / "python.exe").is_file():
        raise ValueError("embedded python/python.exe is missing")
    for source in sorted(runtime_root.rglob("*"), key=lambda item: item.as_posix()):
        if not source.is_file():
            continue
        relative = source.relative_to(repo_root)
        if _is_bytecode(relative):
            continue
        destination = stage_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1

    if not (stage_root / "app.py").is_file():
        raise ValueError("release stage does not contain app.py")
    return copied


def _stage_files(stage_root: Path) -> list[Path]:
    files = [
        path for path in stage_root.rglob("*")
        if path.is_file() and not _is_bytecode(path.relative_to(stage_root))
    ]
    files.sort(key=lambda item: item.relative_to(stage_root).as_posix())

    casefolded: dict[str, str] = {}
    for path in files:
        name = path.relative_to(stage_root).as_posix()
        previous = casefolded.setdefault(name.casefold(), name)
        if previous != name:
            raise ValueError(
                f"release contains Windows case-colliding paths: {previous}, {name}"
            )
    return files


def content_sha256(stage_root: Path) -> str:
    """Hash sorted relative paths and file bytes, ignoring filesystem metadata."""
    stage_root = stage_root.resolve()
    digest = hashlib.sha256()
    for source in _stage_files(stage_root):
        name = source.relative_to(stage_root).as_posix().encode("utf-8")
        file_digest = hashlib.sha256()
        with source.open("rb") as input_file:
            while chunk := input_file.read(COPY_CHUNK_SIZE):
                file_digest.update(chunk)
        digest.update(file_digest.hexdigest().encode("ascii"))
        digest.update(b"  ")
        digest.update(name)
        digest.update(b"\0")
    return digest.hexdigest()


def create_zip(
    stage_root: Path,
    destination: Path,
    *,
    archive_prefix: str = "",
) -> tuple[int, int, set[str]]:
    """Archive a tree in sorted order; content identity is computed separately."""
    stage_root = stage_root.resolve()
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)

    names: set[str] = set()
    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=True,
    ) as archive:
        for source in _stage_files(stage_root):
            name = source.relative_to(stage_root).as_posix()
            if archive_prefix:
                name = f"{archive_prefix}/{name}"
            names.add(name)
            archive.write(source, name)

    payload_size = destination.stat().st_size
    return len(names), payload_size, names


def build_archives(stage_root: Path, output_root: Path) -> dict[str, dict]:
    """Build full first, then folder components and the remaining app archive."""
    stage_root = stage_root.resolve()
    output_root = output_root.resolve()
    _safe_recreate_directory(output_root, forbidden=stage_root)

    result: dict[str, dict] = {}

    def build(name: str, source: Path) -> set[str]:
        destination = output_root / ARCHIVE_NAMES[name]
        sha256 = content_sha256(source)
        prefix = "" if source == stage_root else source.relative_to(stage_root).as_posix()
        count, size, release_names = create_zip(
            source,
            destination,
            archive_prefix=prefix,
        )
        result[name] = {
            "file": destination.name,
            "size": size,
            "sha256": sha256,
            "entries": count,
        }
        print(
            f"Built {name}: {destination.name}, {size / 1048576:.2f} MiB, "
            f"content_sha256={sha256[:16]}, entries={count}",
            flush=True,
        )
        return release_names

    full_names = build("full", stage_root)
    component_names: set[str] = set()
    for name, folder in COMPONENT_FOLDERS.items():
        component_root = stage_root / folder
        if not component_root.is_dir():
            raise ValueError(f"release component folder is missing: {folder}")
        names = build(name, component_root)
        overlap = component_names.intersection(names)
        if overlap:
            raise ValueError(f"component archives overlap: {sorted(overlap)[:3]}")
        component_names.update(names)
        shutil.rmtree(component_root)

    app_names = build("app", stage_root)
    overlap = component_names.intersection(app_names)
    if overlap:
        raise ValueError(f"app archive overlaps components: {sorted(overlap)[:3]}")
    reconstructed = component_names.union(app_names)
    if reconstructed != full_names:
        missing = sorted(full_names - reconstructed)[:3]
        extra = sorted(reconstructed - full_names)[:3]
        raise ValueError(
            f"component archives do not reconstruct full release: "
            f"missing={missing}, extra={extra}"
        )
    metadata_path = output_root / "release-metadata.json"
    metadata_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--output", default="dist")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo).resolve()
    stage_root = Path(args.stage).resolve()
    output_root = Path(args.output).resolve()
    copied = prepare_release_stage(repo_root, stage_root)
    print(f"Prepared release stage: {copied} files", flush=True)
    build_archives(stage_root, output_root)


if __name__ == "__main__":
    main()
