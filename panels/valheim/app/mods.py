from __future__ import annotations

from datetime import datetime
from pathlib import Path, PurePosixPath
import hashlib
import json
import re
import secrets
import shutil
import stat
import tempfile
import zipfile

from .storage import inside, read_json, write_json


DEPENDENCY = re.compile(r"^(?P<owner>[A-Za-z0-9_]+)-(?P<name>[A-Za-z0-9_]+)-(?P<version>\d+\.\d+\.\d+)$")
EDITABLE_CONFIG_SUFFIXES = {".cfg", ".json", ".toml", ".yaml", ".yml"}
LOADER_FILES = {
    "BepInEx/core/BepInEx.dll",
    "BepInEx/core/BepInEx.Preloader.dll",
    "doorstop_libs/libdoorstop_x64.so",
}
LOADER_TOP_LEVEL = {
    "BepInEx", "unstripped_corlib", "doorstop_libs", "doorstop_config.ini",
    ".doorstop_version", "start_game_bepinex.sh", "start_server_bepinex.sh", "winhttp.dll", "version.dll",
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def safe_package_name(value: object, fallback: str) -> str:
    name = str(value or fallback).strip()
    if not name or len(name) > 120 or any(ord(character) < 32 for character in name):
        raise ValueError("모드 이름을 확인해주세요.")
    return name


def semantic_version(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", str(value or ""))
    return tuple(map(int, match.groups())) if match else None


class ModManager:
    def __init__(self, data_root: Path, server_root: Path, max_bytes: int):
        self.server = server_root
        self.root = data_root / "mods"
        self.trash = data_root / "mod-trash"
        self.exports = data_root / "exports"
        self.max_bytes = max_bytes
        for path in (self.root, self.trash, self.exports):
            path.mkdir(parents=True, exist_ok=True)

    def package_dir(self, package_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", str(package_id or "")):
            raise ValueError("올바른 모드 ID가 아닙니다.")
        return inside(self.root, package_id)

    def packages(self) -> list[dict]:
        packages = []
        for directory in sorted(self.root.iterdir()):
            if directory.is_symlink() or not directory.is_dir() or not re.fullmatch(r"[0-9a-f]{32}", directory.name):
                continue
            metadata_file = directory / "package.json"
            if not metadata_file.is_file():
                continue
            metadata = read_json(metadata_file, {})
            package = self._normalize_metadata(metadata, directory.name)
            packages.append(package)
        return packages

    def package(self, package_id: str) -> dict:
        found = next((package for package in self.packages() if package["id"] == package_id), None)
        if not found:
            raise FileNotFoundError("모드를 찾을 수 없습니다.")
        return found

    def public_packages(self) -> dict:
        packages = self.packages()
        result = []
        for package in packages:
            public = {key: value for key, value in package.items() if key not in {"hash", "deployed"}}
            public["issue"] = self.enable_issue(package, packages)
            public["file_count"] = len(list(self._source_files(package)))
            result.append(public)
        return {
            "loader_ready": self.loader_ready(),
            "enabled_count": sum(1 for package in packages if package["enabled"] and not package["is_loader"]),
            "registered_count": sum(1 for package in packages if not package["is_loader"]),
            "packages": sorted(result, key=lambda item: (not item["is_loader"], item["name"].casefold())),
        }

    def loader_ready(self, overlay: Path | None = None) -> bool:
        return all(self._overlay_file(relative, overlay).is_file() for relative in LOADER_FILES)

    def enable_issue(self, package: dict, packages: list[dict] | None = None) -> str | None:
        if package["enabled"]:
            return None
        packages = packages or self.packages()
        source = self.package_dir(package["id"]) / "files"
        if not any(path.suffix.casefold() == ".dll" for path in self._source_files(package)):
            return "보관된 BepInEx DLL이 없습니다. 원본 ZIP 또는 DLL을 다시 설치해주세요."
        if not self.loader_ready(source if package["is_loader"] else None):
            return "Linux용 BepInEx 로더를 먼저 설치하고 켜주세요."
        for dependency in package["dependencies"]:
            if not any(other["id"] != package["id"] and other["enabled"] and self.satisfies(other, dependency)
                       for other in packages):
                return f"먼저 설치하고 켜야 할 모드: {dependency}"
        for file in self._source_files(package):
            relative = file.relative_to(source).as_posix()
            target = inside(self.server, relative)
            if relative.casefold().startswith("bepinex/config/"):
                continue
            if target.exists():
                return f"같은 위치에 파일이 있습니다: {relative}"
        return None

    def install_files(self, uploads: list[tuple[Path, str]]) -> list[dict]:
        results = []
        pending = []
        for upload, original_name in uploads:
            try:
                digest = file_hash(upload)
                known = self.packages()
                existing = next((package for package in known if package["hash"] == digest), None)
                if existing:
                    results.append({"name": existing["name"], "enabled": existing["enabled"],
                                    "message": "이미 등록된 동일한 파일입니다."})
                    continue
                package = self._import(upload, original_name)
                duplicate = next((item for item in known if self._same_package(item, package)), None)
                if duplicate:
                    self._discard(package)
                    results.append({"name": package["name"], "enabled": False,
                                    "message": "이미 등록된 모드입니다. 관리 메뉴에서 새 파일로 업데이트해주세요."})
                    continue
                pending.append(package)
            except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
                results.append({"name": original_name, "enabled": False, "message": str(error)})

        progressed = True
        while progressed and pending:
            progressed = False
            for package in sorted(pending, key=lambda item: not item["is_loader"]):
                issue = self.enable_issue(package)
                if issue:
                    continue
                try:
                    self.set_enabled(package["id"], True)
                    results.append({"name": package["name"], "enabled": True,
                                    "message": "설치 완료 · 다음 서버 시작부터 적용됩니다."})
                except (OSError, ValueError) as error:
                    results.append({"name": package["name"], "enabled": False,
                                    "message": f"파일은 등록했지만 켜지 못했습니다. {error}"})
                pending.remove(package)
                progressed = True
                break
        for package in pending:
            results.append({"name": package["name"], "enabled": False,
                            "message": f"파일은 등록했습니다. {self.enable_issue(package)}"})
        return results

    def set_enabled(self, package_id: str, enabled: bool, *, check_dependents: bool = True) -> dict:
        package = self.package(package_id)
        if package["enabled"] == enabled:
            return package
        packages = self.packages()
        if enabled:
            issue = self.enable_issue(package, packages)
            if issue:
                raise ValueError(issue)
            source = self.package_dir(package_id) / "files"
            deployed = {}
            try:
                for file in self._source_files(package):
                    relative = file.relative_to(source).as_posix()
                    target = inside(self.server, relative)
                    if relative.casefold().startswith("bepinex/config/") and target.exists():
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, target)
                    deployed[relative] = file_hash(target)
                package["enabled"] = True
                package["deployed"] = deployed
                self._save(package)
            except BaseException:
                for relative in deployed:
                    inside(self.server, relative).unlink(missing_ok=True)
                raise
        else:
            if check_dependents:
                self._validate_disable(package, packages)
            for relative, digest in package["deployed"].items():
                target = inside(self.server, relative)
                if target.exists() and file_hash(target) != digest:
                    raise ValueError(f"설치 후 변경된 모드 파일을 먼저 보관해주세요: {relative}")
            for relative in package["deployed"]:
                inside(self.server, relative).unlink(missing_ok=True)
            package["enabled"] = False
            package["deployed"] = {}
            self._save(package)
        return package

    def update(self, package_id: str, upload: Path, original_name: str) -> dict:
        current = self.package(package_id)
        replacement = self._import(upload, original_name, allow_duplicate=True)
        if not self._same_package(current, replacement):
            self._discard(replacement)
            raise ValueError("선택한 파일이 현재 모드와 다른 패키지입니다.")
        was_enabled = current["enabled"]
        try:
            if was_enabled:
                self._validate_disable(current, self.packages(), replacement)
                self.set_enabled(current["id"], False, check_dependents=False)
                self.set_enabled(replacement["id"], True)
            self._discard(current, trash=True)
            return self.package(replacement["id"])
        except BaseException:
            active_replacement = next((item for item in self.packages() if item["id"] == replacement["id"]), None)
            if active_replacement and active_replacement["enabled"]:
                self.set_enabled(replacement["id"], False, check_dependents=False)
            self._discard(replacement)
            if was_enabled and not self.package(current["id"])["enabled"]:
                self.set_enabled(current["id"], True)
            raise

    def remove(self, package_id: str) -> None:
        package = self.package(package_id)
        if package["enabled"]:
            self.set_enabled(package_id, False)
            package = self.package(package_id)
        self._validate_disable(package, self.packages())
        self._discard(package, trash=True)

    def disable_all(self) -> int:
        packages = self.packages()
        enabled = [package for package in packages if package["enabled"]]
        tracked = {relative for package in enabled for relative in package["deployed"]}
        bepinex = self.server / "BepInEx"
        if bepinex.exists():
            untracked = [path for path in bepinex.rglob("*.dll") if not path.is_symlink()
                         and path.relative_to(self.server).as_posix() not in tracked]
            if untracked:
                raise ValueError("수동 설치한 미등록 모드가 있습니다. 서버 폴더에서 먼저 별도로 보관해주세요.")
        count = 0
        for package in sorted(enabled, key=lambda item: item["is_loader"]):
            self.set_enabled(package["id"], False, check_dependents=False)
            count += 1
        return count

    def configuration_files(self) -> list[dict]:
        root = self.server / "BepInEx" / "config"
        if not root.exists():
            return []
        files = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file() or path.suffix.casefold() not in EDITABLE_CONFIG_SUFFIXES:
                continue
            files.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size,
                          "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")})
        return files

    def read_configuration(self, relative: str) -> str:
        path = self._configuration_path(relative)
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("1MB 이하의 모드 설정 파일만 편집할 수 있습니다.")
        return path.read_text(encoding="utf-8")

    def write_configuration(self, relative: str, content: str) -> None:
        if len(content.encode("utf-8")) > 1024 * 1024:
            raise ValueError("1MB 이하의 모드 설정 파일만 저장할 수 있습니다.")
        path = self._configuration_path(relative)
        backup = path.with_name(f"{path.name}.techtim-{datetime.now():%Y%m%d-%H%M%S}.bak")
        shutil.copy2(path, backup)
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def export_pack(self) -> tuple[Path, str]:
        packages = self.packages()
        if not packages:
            raise ValueError("내보낼 모드가 없습니다.")
        handle = tempfile.NamedTemporaryFile(prefix=".valheim-modpack-", suffix=".zip", dir=self.exports, delete=False)
        destination = Path(handle.name)
        handle.close()
        try:
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                for package in packages:
                    clean = dict(package)
                    clean["enabled"] = False
                    clean["deployed"] = {}
                    archive.writestr(f"{package['id']}/package.json", json.dumps(clean, ensure_ascii=False, indent=2))
                    source = self.package_dir(package["id"]) / "files"
                    for file in self._source_files(package):
                        archive.write(file, f"{package['id']}/files/{file.relative_to(source).as_posix()}")
            return destination, f"TechTim-Valheim-modpack-{datetime.now():%Y%m%d-%H%M%S}.zip"
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    def import_pack(self, archive: Path) -> int:
        imported = []
        try:
            with tempfile.TemporaryDirectory(prefix=".modpack-", dir=self.root) as temporary:
                staging = Path(temporary)
                self._extract(archive, staging)
                for directory in sorted(staging.iterdir()):
                    if not directory.is_dir() or directory.is_symlink():
                        raise ValueError("TechTim 모드팩 형식이 아닙니다.")
                    metadata_file = directory / "package.json"
                    files = directory / "files"
                    if not metadata_file.is_file() or not files.is_dir() or not any(path.is_file() for path in files.rglob("*")):
                        raise ValueError("모드팩에 필요한 패키지 파일이 없습니다.")
                    new_id = secrets.token_hex(16)
                    metadata = read_json(metadata_file, {})
                    metadata["id"] = new_id
                    package = self._normalize_metadata(metadata, new_id)
                    package["enabled"] = False
                    package["deployed"] = {}
                    self._validate_stored_files(files, package)
                    if any(self._same_package(package, known) for known in self.packages() + imported):
                        raise ValueError(f"이미 등록된 모드가 모드팩에 포함되어 있습니다: {package['name']}")
                    destination = self.package_dir(new_id)
                    destination.mkdir()
                    shutil.copytree(files, destination / "files")
                    self._save(package)
                    imported.append(package)
        except BaseException:
            for package in imported:
                self._discard(package)
            raise
        return len(imported)

    def diagnose(self) -> str:
        packages = self.packages()
        lines = [f"서버 빌드: {self._server_build() or '확인 불가'}",
                 f"BepInEx 로더: {'준비됨' if self.loader_ready() else '미설치 또는 꺼짐'}"]
        for package in packages:
            state = "켜짐" if package["enabled"] else "꺼짐"
            issue = self.enable_issue(package, packages)
            detail = f" · {issue}" if issue else ""
            lines.append(f"{package['name']} {package['version'] or ''}: {state}{detail}")
        lines.append("클라이언트 설치 필요 여부와 게임 버전 호환성은 각 모드 제작자의 안내도 확인해주세요.")
        return "\n".join(lines)

    def satisfies(self, package: dict, dependency: str) -> bool:
        match = DEPENDENCY.fullmatch(dependency)
        installed = semantic_version(package["version"])
        minimum = semantic_version(match.group("version")) if match else None
        return bool(match and installed and minimum and package["package_id"] == f"{match.group('owner')}-{match.group('name')}"
                    and installed >= minimum)

    def _import(self, upload: Path, original_name: str, allow_duplicate: bool = False) -> dict:
        suffix = Path(original_name).suffix.casefold()
        if suffix not in {".zip", ".dll"}:
            raise ValueError("발헤임 서버용 ZIP 또는 DLL 파일만 설치할 수 있습니다.")
        package_id = secrets.token_hex(16)
        directory = self.package_dir(package_id)
        directory.mkdir()
        files_root = directory / "files"
        files_root.mkdir()
        fallback = Path(original_name).stem
        package = {"id": package_id, "name": fallback, "version": "", "package_id": "",
                   "is_loader": False, "source": original_name, "hash": file_hash(upload),
                   "dependencies": [], "enabled": False, "deployed": {}}
        try:
            if suffix == ".dll":
                destination = inside(files_root, f"BepInEx/plugins/{package_id}/{Path(original_name).name}")
                destination.parent.mkdir(parents=True)
                shutil.copy2(upload, destination)
            else:
                with tempfile.TemporaryDirectory(prefix=".archive-", dir=self.root) as temporary:
                    extracted = Path(temporary)
                    self._extract(upload, extracted)
                    manifest = self._manifest(extracted)
                    if manifest:
                        package["name"] = safe_package_name(manifest.get("name"), fallback)
                        package["version"] = str(manifest.get("version_number") or "")[:40]
                        dependencies = manifest.get("dependencies") or []
                        if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
                            raise ValueError("manifest.json의 dependencies 형식이 올바르지 않습니다.")
                        package["dependencies"] = list(dict.fromkeys(dependencies))[:100]
                    package["package_id"] = self._identity(original_name, package)
                    mapped = self._map_archive(extracted, package_id)
                    for source, relative in mapped:
                        destination = inside(files_root, relative)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, destination)
            self._validate_stored_files(files_root, package)
            if not allow_duplicate and any(self._same_package(package, known) for known in self.packages()):
                raise ValueError("이미 등록된 모드입니다. 새 파일로 업데이트해주세요.")
            self._save(package)
            return package
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def _map_archive(self, extracted: Path, package_id: str) -> list[tuple[Path, str]]:
        files = [(path, path.relative_to(extracted).as_posix()) for path in extracted.rglob("*") if path.is_file()]
        roots = {relative[:relative.casefold().index("bepinex/")] for _, relative in files if "bepinex/" in relative.casefold()}
        if len(roots) > 1:
            raise ValueError("여러 BepInEx 루트가 있는 ZIP입니다. 패키지를 나누어 설치해주세요.")
        mapped = []
        for source, relative in files:
            if self._documentation(relative):
                continue
            if not roots:
                mapped.append((source, f"BepInEx/plugins/{package_id}/{relative}"))
                continue
            root = next(iter(roots))
            if not relative.casefold().startswith(root.casefold()):
                raise ValueError(f"BepInEx 루트 밖에 부속 파일이 있습니다: {relative}")
            target = relative[len(root):]
            if self._documentation(target):
                continue
            if target.split("/", 1)[0].casefold() not in {item.casefold() for item in LOADER_TOP_LEVEL}:
                raise ValueError(f"설치 위치가 불명확한 파일입니다: {target}")
            mapped.append((source, target))
        return mapped

    def _extract(self, archive: Path, destination: Path) -> None:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) > 10000 or sum(entry.file_size for entry in entries) > self.max_bytes:
                raise ValueError("압축 파일의 개수 또는 압축 해제 크기가 제한을 초과했습니다.")
            seen = set()
            for entry in entries:
                name = entry.filename.rstrip("/")
                if not name:
                    continue
                normalized = PurePosixPath(name)
                if (normalized.is_absolute() or any(part in {"", ".", ".."} for part in normalized.parts)
                        or name.casefold() in seen or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1):
                    raise ValueError("압축 파일에 안전하지 않은 경로, 링크, 중복 또는 암호화 항목이 있습니다.")
                seen.add(name.casefold())
                target = inside(destination, name)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(entry) as reader, target.open("xb") as writer:
                        shutil.copyfileobj(reader, writer, length=1024 * 1024)

    def _manifest(self, extracted: Path) -> dict | None:
        manifests = sorted((path for path in extracted.rglob("manifest.json") if path.is_file()),
                           key=lambda path: len(path.parts))
        if not manifests:
            return None
        if manifests[0].stat().st_size > 1024 * 1024:
            raise ValueError("manifest.json 파일이 너무 큽니다.")
        value = json.loads(manifests[0].read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("manifest.json 형식이 올바르지 않습니다.")
        return value

    def _normalize_metadata(self, value: dict, expected_id: str) -> dict:
        if not isinstance(value, dict) or value.get("id") not in {expected_id, None}:
            raise ValueError("모드 등록 정보가 올바르지 않습니다.")
        deployed = value.get("deployed") or {}
        if not isinstance(deployed, dict) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in deployed.items()):
            raise ValueError("모드 배포 정보가 올바르지 않습니다.")
        dependencies = value.get("dependencies") or []
        if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
            raise ValueError("모드 의존성 정보가 올바르지 않습니다.")
        return {"id": expected_id, "name": safe_package_name(value.get("name"), expected_id),
                "version": str(value.get("version") or "")[:40], "package_id": str(value.get("package_id") or "")[:160],
                "is_loader": bool(value.get("is_loader")), "source": str(value.get("source") or "로컬 파일")[:255],
                "hash": str(value.get("hash") or "")[:128], "dependencies": dependencies[:100],
                "enabled": bool(value.get("enabled")), "deployed": deployed}

    def _validate_stored_files(self, files_root: Path, package: dict) -> None:
        relatives = {path.relative_to(files_root).as_posix() for path in files_root.rglob("*")
                     if path.is_file() and not path.is_symlink()}
        if not any(relative.casefold().endswith(".dll") for relative in relatives):
            raise ValueError("설치 가능한 BepInEx DLL을 찾지 못했습니다.")
        allowed = {item.casefold() for item in LOADER_TOP_LEVEL}
        if any(relative.split("/", 1)[0].casefold() not in allowed for relative in relatives):
            raise ValueError("모드팩에 서버 설치 위치가 허용되지 않은 파일이 있습니다.")
        folded = {relative.casefold() for relative in relatives}
        package["is_loader"] = "bepinex/core/bepinex.dll" in folded
        if package["is_loader"] and not {item.casefold() for item in LOADER_FILES}.issubset(folded):
            raise ValueError("GCP에서는 Linux 서버용 BepInEx 패키지가 필요합니다. Linux doorstop 파일을 확인해주세요.")

    def _save(self, package: dict) -> None:
        write_json(self.package_dir(package["id"]) / "package.json", package)

    def _source_files(self, package: dict):
        root = self.package_dir(package["id"]) / "files"
        return (path for path in sorted(root.rglob("*")) if path.is_file() and not path.is_symlink())

    def _discard(self, package: dict, trash: bool = False) -> None:
        source = self.package_dir(package["id"])
        if not source.exists():
            return
        if trash:
            destination = self.trash / f"{datetime.now():%Y%m%d-%H%M%S}-{package['id']}"
            source.replace(destination)
        else:
            shutil.rmtree(source)

    def _validate_disable(self, package: dict, packages: list[dict], replacement: dict | None = None) -> None:
        others = [item for item in packages if item["enabled"] and item["id"] != package["id"]]
        if package["is_loader"] and others and not (replacement and replacement["is_loader"]):
            raise ValueError("다른 모드가 사용 중입니다. 플러그인을 먼저 끄거나 전체 비활성화를 이용해주세요.")
        for other in others:
            for dependency in other["dependencies"]:
                if self.satisfies(package, dependency) and not (replacement and self.satisfies(replacement, dependency)):
                    raise ValueError(f"{other['name']} 모드가 이 패키지에 의존합니다. 해당 모드를 먼저 꺼주세요.")

    def _configuration_path(self, relative: str) -> Path:
        root = self.server / "BepInEx" / "config"
        path = inside(root, relative, file_only=True)
        if path.suffix.casefold() not in EDITABLE_CONFIG_SUFFIXES:
            raise ValueError("지원하지 않는 모드 설정 파일 형식입니다.")
        return path

    def _overlay_file(self, relative: str, overlay: Path | None) -> Path:
        if overlay:
            candidate = inside(overlay, relative)
            if candidate.is_file():
                return candidate
        return inside(self.server, relative)

    @staticmethod
    def _documentation(relative: str) -> bool:
        if "/" in relative:
            return False
        name = relative.casefold()
        return name in {"manifest.json", "icon.png"} or name.startswith(("readme", "changelog", "license"))

    @staticmethod
    def _identity(original_name: str, package: dict) -> str:
        match = DEPENDENCY.fullmatch(Path(original_name).stem)
        if match and match.group("name") == package["name"] and match.group("version") == package["version"]:
            return f"{match.group('owner')}-{match.group('name')}"
        return ""

    @staticmethod
    def _same_package(left: dict, right: dict) -> bool:
        if left["package_id"] and right["package_id"]:
            return left["package_id"] == right["package_id"]
        return left["name"].casefold() == right["name"].casefold()

    def _server_build(self) -> str:
        manifest = self.server / "steamapps" / "appmanifest_896660.acf"
        if not manifest.is_file():
            return ""
        match = re.search(r'"buildid"\s+"(\d+)"', manifest.read_text(errors="replace"))
        return match.group(1) if match else ""
