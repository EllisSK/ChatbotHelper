"""Discover readable project context without executing project code."""

from __future__ import annotations

import tokenize
from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from io import BytesIO
from pathlib import Path

from pathspec import GitIgnoreSpec


@dataclass(frozen=True)
class SourceFile:
    path: str
    content: str
    size_bytes: int


@dataclass
class DiscoveryResult:
    root: Path
    files: dict[str, SourceFile]
    excluded: dict[str, str]
    warnings: list[str]


_TEXT_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".md",
        ".rst",
        ".txt",
        ".toml",
        ".ini",
        ".cfg",
        ".yaml",
        ".yml",
        ".json",
        ".xml",
        ".csv",
        ".sql",
    }
)
_TEXT_NAMES = frozenset({"readme", "license", "makefile", "dockerfile"})
_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".tox",
        ".nox",
        "node_modules",
        "build",
        "dist",
        ".chatbot-helper",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".uv",
    }
)
_CREDENTIAL_DIRS = frozenset({".ssh", ".aws", ".azure", ".gnupg", ".kube"})
_CREDENTIAL_PATTERNS = (
    ".env*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".netrc",
    ".pypirc",
    "credentials",
    "credentials.*",
    "secrets",
    "secrets.*",
    "token.json",
    "tokens.json",
    "service-account*.json",
    "service_account*.json",
)


@dataclass(frozen=True)
class _IgnoreLayer:
    base: str
    spec: GitIgnoreSpec
    source: str


def _ignore_reason(path: str, layers: Sequence[_IgnoreLayer]) -> str | None:
    """A deeper ignore file can override matching rules of its own kind."""
    ignored = False
    reason = None
    for layer in layers:
        scoped = path[len(layer.base) + 1 :] if layer.base else path
        match = layer.spec.check_file(scoped, separators=("/",))
        if match.include is not None:
            ignored = match.include
            reason = f"ignored by {layer.source}" if ignored else None
    return reason if ignored else None


def _credential_reason(name: str, *, is_directory: bool) -> str | None:
    lowered = name.casefold()
    if is_directory and lowered in _CREDENTIAL_DIRS:
        return "credential directory"
    if any(fnmatchcase(lowered, pattern) for pattern in _CREDENTIAL_PATTERNS):
        return "possible credential file or directory"
    return None


def discover(
    root: Path,
    *,
    excludes: Sequence[str] = (),
    max_file_bytes: int = 200_000,
) -> DiscoveryResult:
    """Inventory text files using safe defaults and scoped Git ignore rules.

    Ignored directories are reported once with a trailing slash and are not
    traversed. Both ignore-file families operate independently: a negation in
    ``.chatbothelperignore`` cannot override ``.gitignore`` or safety defaults.
    The supplied root may be a link; symlinks and Windows directory junctions
    inside it are never followed.
    """
    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {root}")
    if max_file_bytes < 1:
        raise ValueError("max_file_bytes must be positive")
    result = DiscoveryResult(root=root, files={}, excluded={}, warnings=[])
    configured = (
        (_IgnoreLayer("", GitIgnoreSpec.from_lines(excludes), "configured exclusions"),)
        if excludes
        else ()
    )

    def read_ignore(directory: Path, name: str) -> _IgnoreLayer | None:
        ignore_file = directory / name
        if ignore_file.is_symlink() or ignore_file.is_junction() or not ignore_file.is_file():
            return None
        source = ignore_file.relative_to(root).as_posix()
        try:
            # Ignore files are small configuration inputs, never project code.
            if ignore_file.stat().st_size > max_file_bytes:
                result.warnings.append(f"Ignore file exceeds size limit: {source}")
                return None
            lines = ignore_file.read_text(encoding="utf-8-sig").splitlines()
            spec = GitIgnoreSpec.from_lines(lines)
        except (OSError, UnicodeError, ValueError) as exc:
            result.warnings.append(f"Could not read ignore rules in {source}: {exc}")
            return None
        base = directory.relative_to(root).as_posix()
        return _IgnoreLayer("" if base == "." else base, spec, source)

    def walk(
        directory: Path,
        git_layers: tuple[_IgnoreLayer, ...],
        helper_layers: tuple[_IgnoreLayer, ...],
    ) -> None:
        for name, family in ((".gitignore", "git"), (".chatbothelperignore", "helper")):
            layer = read_ignore(directory, name)
            if layer:
                if family == "git":
                    git_layers = (*git_layers, layer)
                else:
                    helper_layers = (*helper_layers, layer)
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
        except OSError as exc:
            relative = directory.relative_to(root).as_posix()
            result.warnings.append(f"Could not list {relative}: {exc}")
            return
        for entry in entries:
            path = entry.relative_to(root).as_posix()
            try:
                if entry.is_symlink():
                    result.excluded[path] = "symbolic link"
                    continue
                if entry.is_junction():
                    result.excluded[f"{path}/"] = "directory junction"
                    continue
                is_directory = entry.is_dir()
                reported_path = f"{path}/" if is_directory else path
                credential_reason = _credential_reason(entry.name, is_directory=is_directory)
                if credential_reason:
                    result.excluded[reported_path] = credential_reason
                    continue
                if is_directory and (
                    entry.name.casefold() in _EXCLUDED_DIRS
                    or entry.name.casefold().endswith(".egg-info")
                ):
                    result.excluded[reported_path] = "default excluded directory"
                    continue
                reason = (
                    _ignore_reason(reported_path, git_layers)
                    or _ignore_reason(reported_path, helper_layers)
                    or _ignore_reason(reported_path, configured)
                )
                if reason:
                    result.excluded[reported_path] = reason
                    continue
                if is_directory:
                    walk(entry, git_layers, helper_layers)
                    continue
                if not entry.is_file():
                    result.excluded[path] = "not a regular file"
                    continue
                if (
                    entry.suffix.casefold() not in _TEXT_SUFFIXES
                    and entry.name.casefold() not in _TEXT_NAMES
                ):
                    result.excluded[path] = "unsupported file type"
                    continue
                if entry.stat().st_size > max_file_bytes:
                    result.excluded[path] = f"exceeds {max_file_bytes} byte file limit"
                    continue
                with entry.open("rb") as handle:
                    data = handle.read(max_file_bytes + 1)
                if len(data) > max_file_bytes:
                    result.excluded[path] = f"exceeds {max_file_bytes} byte file limit"
                    continue
                if b"\0" in data:
                    result.excluded[path] = "binary content"
                    continue
                encoding = "utf-8-sig"
                if entry.suffix.casefold() in {".py", ".pyi"}:
                    encoding, _ = tokenize.detect_encoding(BytesIO(data).readline)
                content = data.decode(encoding)
            except (UnicodeError, SyntaxError, LookupError) as exc:
                result.excluded[path] = "undecodable text"
                result.warnings.append(f"Could not decode {path}: {exc}")
                continue
            except OSError as exc:
                result.excluded[path] = "unreadable file or directory"
                result.warnings.append(f"Could not read {path}: {exc}")
                continue
            result.files[path] = SourceFile(path=path, content=content, size_bytes=len(data))

    walk(root, (), ())
    return result
