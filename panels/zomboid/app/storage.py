"""Atomic panel state and bounded, traversal-safe world archives."""
from pathlib import Path, PurePosixPath
from typing import Any
import json
import os
import secrets
import shutil
import stat
import zipfile


def write_json(path: Path, payload: Any) -> None:
    write_bytes(path, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode())


def write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("xb") as stream:
            os.chmod(temporary, 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    # Invalid existing state must surface as an error, never reset credentials or settings.
    return json.loads(path.read_text(encoding="utf-8"))


def inside(root: Path, relative: str, *, file_only: bool = False) -> Path:
    if not relative or "\\" in relative or "\x00" in relative:
        raise ValueError("올바른 상대 경로를 입력해주세요.")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or any(p in {"..", "."} for p in relative.split("/")):
        raise ValueError("데이터 폴더 밖으로 이동할 수 없습니다.")
    candidate = root.joinpath(*parts.parts)
    # Reject even in-root symlinks, including symlinked parent directories.
    current = root
    for part in parts.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("심볼릭 링크는 사용할 수 없습니다.")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("데이터 폴더 밖으로 이동할 수 없습니다.")
    if file_only and not candidate.is_file():
        raise FileNotFoundError("파일을 찾을 수 없습니다.")
    return candidate


def worlds(save_dir: Path) -> list[dict]:
    root = save_dir / "worlds_local"
    if not root.exists():
        return []
    names = {p.stem for ext in ("*.db", "*.fwl") for p in root.glob(ext) if not p.is_symlink()}
    result = []
    for name in sorted(names, key=str.casefold):
        files = [inside(root, name + suffix) for suffix in (".db", ".fwl")]
        found = [p for p in files if p.is_file()]
        result.append({"name": name, "complete": len(found) == 2,
                       "size": sum(p.stat().st_size for p in found),
                       "modified_at": max((p.stat().st_mtime for p in found), default=0)})
    return result


def create_archive(root: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".partial")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            for path in sorted(root.rglob("*")):
                if path.is_symlink():
                    raise ValueError("심볼릭 링크가 포함된 데이터는 백업할 수 없습니다.")
                if path.is_file():
                    archive.write(path, path.relative_to(root).as_posix())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def extract_archive(source: Path, destination: Path, max_bytes: int) -> None:
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if len(entries) > 10000 or sum(p.file_size for p in entries) > max_bytes:
            raise ValueError("백업의 파일 개수 또는 압축 해제 크기가 제한을 초과했습니다.")
        if shutil.disk_usage(destination.parent).free < sum(p.file_size for p in entries) + 64 * 1024**2:
            raise ValueError("복원을 위한 디스크 여유 공간이 부족합니다.")
        seen = set()
        for item in entries:
            name = item.filename.rstrip("/")
            target = inside(destination, name)
            if name in seen or stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                raise ValueError("중복 경로, 링크 또는 암호화 파일이 포함된 백업입니다.")
            seen.add(name)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as reader, target.open("xb") as writer:
                    shutil.copyfileobj(reader, writer, length=1024 * 1024)
    if not any(w["complete"] for w in worlds(destination)):
        raise ValueError("worlds_local 폴더 안에 .db와 .fwl 월드 파일 쌍이 필요합니다.")


def replace_directory(current: Path, staged: Path) -> None:
    previous = current.with_name(f".{current.name}-previous-{secrets.token_hex(6)}")
    existed = current.exists()
    if existed:
        current.rename(previous)
    try:
        staged.rename(current)
    except BaseException:
        if existed:
            previous.rename(current)
        raise
    if existed:
        shutil.rmtree(previous)
