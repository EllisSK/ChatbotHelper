"""Deterministic, local context recommendations and requested-path handling."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import cache

from .discovery import SourceFile
from .python_context import PythonModule, dependencies


@dataclass(frozen=True)
class Candidate:
    path: str
    score: float
    reasons: tuple[str, ...]
    pinned: bool = False


_STOP_WORDS = frozenset(
    "a an and are as at be by can change code could file files fix for from have "
    "help how i in is it make me my need of on or please python should that the "
    "this to update use want we when with would".split()
)


def _words(value: str) -> set[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return {
        word.lower()
        for word in re.findall(r"[A-Za-z][A-Za-z0-9]*", value)
        if len(word) > 1 and word.lower() not in _STOP_WORDS
    }


def _normalise_pattern(value: str) -> str:
    pattern = value.strip().replace("\\", "/")
    while pattern.startswith("./"):
        pattern = pattern[2:]
    if (
        not pattern
        or pattern.startswith(("/", "~"))
        or re.match(r"^[A-Za-z]:", pattern)
        or ".." in pattern.split("/")
        or "\x00" in pattern
    ):
        raise ValueError(
            f"Unsafe path {value!r}. Use paths relative to the project root, "
            "without drive letters, absolute paths, or '..'."
        )
    return pattern


def _glob_matches(path: str, pattern: str) -> bool:
    """Match shell-style path segments, allowing ** to match zero directories."""
    path_parts = tuple(path.split("/"))
    pattern_parts = tuple(pattern.split("/"))

    @cache
    def match(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        part = pattern_parts[pattern_index]
        if part == "**":
            return match(path_index, pattern_index + 1) or (
                path_index < len(path_parts) and match(path_index + 1, pattern_index)
            )
        return (
            path_index < len(path_parts)
            and fnmatchcase(path_parts[path_index], part)
            and match(path_index + 1, pattern_index + 1)
        )

    return match(0, 0)


def select_paths(files: Mapping[str, SourceFile], patterns: Sequence[str]) -> list[str]:
    """Expand project-relative paths/globs, rejecting traversal and missing files.

    A directory ending in a slash includes its discovered descendants. Matches
    are deduplicated while preserving request order and sorting each glob.
    """
    selected: list[str] = []
    seen: set[str] = set()
    for original in patterns:
        pattern = _normalise_pattern(original)
        if pattern in files:
            matches = [pattern]
        elif pattern.endswith("/"):
            matches = sorted(path for path in files if path.startswith(pattern))
        else:
            matches = sorted(path for path in files if _glob_matches(path, pattern))
        if not matches:
            raise ValueError(
                f"No available files match {original!r}. Use a relative file path "
                "or a glob such as 'src/**/*.py'; excluded files cannot be selected."
            )
        for path in matches:
            if path not in seen:
                selected.append(path)
                seen.add(path)
    return selected


def _test_identity(path: str) -> str:
    name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if name.startswith("test_"):
        name = name[5:]
    if name.endswith("_test"):
        name = name[:-5]
    return name


def _is_test(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    return (
        "tests" in parts[:-1]
        or "test" in parts[:-1]
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def suggest(
    files: Mapping[str, SourceFile],
    modules: Mapping[str, PythonModule],
    task: str,
    *,
    pinned: Sequence[str] = (),
) -> list[Candidate]:
    """Score all available files; unmatched files remain reviewable at score zero."""
    pinned_paths = set(select_paths(files, pinned))
    task_words = _words(task)
    scores = dict.fromkeys(files, 0.0)
    reasons: dict[str, list[str]] = {path: [] for path in files}
    for path in sorted(files):
        path_matches = task_words & _words(path)
        module = modules.get(path)
        symbol_words = (
            set().union(*(_words(symbol.name) for symbol in module.symbols))
            if module and module.symbols
            else set()
        )
        symbol_matches = task_words & symbol_words
        content_matches = task_words & _words(files[path].content)
        if path_matches:
            scores[path] += 6 * len(path_matches)
            reasons[path].append("Path matches: " + ", ".join(sorted(path_matches)))
        if symbol_matches:
            scores[path] += 4 * len(symbol_matches)
            reasons[path].append("Symbols match: " + ", ".join(sorted(symbol_matches)))
        if content_matches:
            scores[path] += min(3.0, 0.5 * len(content_matches))
            reasons[path].append("Source matches: " + ", ".join(sorted(content_matches)))
        if path in pinned_paths:
            scores[path] += 100.0
            reasons[path].insert(0, "Explicitly selected")

    # Only lexical matches and pins seed relationships; recommendations do not
    # recursively pull the entire transitive import graph into the bundle.
    seeds = sorted(path for path in files if scores[path] > 0 or path in pinned_paths)
    graph = dependencies(modules)
    for path in seeds:
        for dependency in sorted(graph.get(path, ())):
            if dependency in files and dependency != path:
                scores[dependency] += 2.0
                reasons[dependency].append(f"Imported by {path}")
        if _is_test(path):
            continue
        identity = _test_identity(path)
        for test_path in sorted(files):
            if (
                _is_test(test_path)
                and test_path != path
                and (_test_identity(test_path) == identity or path in graph.get(test_path, ()))
            ):
                scores[test_path] += 3.0
                reasons[test_path].append(f"Related tests for {path}")

    return sorted(
        (
            Candidate(
                path=path,
                score=scores[path],
                reasons=tuple(dict.fromkeys(reasons[path])),
                pinned=path in pinned_paths,
            )
            for path in files
        ),
        key=lambda item: (not item.pinned, -item.score, item.path),
    )


_PROSE_PREFIX = re.compile(
    r"^(?:please|here|these|those|the following|i |you |we |can you|could you|"
    r"read |review |inspect |include |request |add |send |upload |look |also )",
    re.IGNORECASE,
)


def _looks_like_path(value: str) -> bool:
    if not value or value.endswith((":", ".", ",", ";")):
        return False
    if _PROSE_PREFIX.match(value) or re.search(r"[\n\r<>|\x00=(){}]", value):
        return False
    basename = value.replace("\\", "/").rsplit("/", 1)[-1]
    return bool(
        re.search(r"\.[A-Za-z0-9][A-Za-z0-9_.*?\[\]-]*$", basename)
        or "/" in value.replace("\\", "/")
        or basename.upper() in {"DOCKERFILE", "MAKEFILE", "LICENSE", "COPYING"}
    )


def parse_requests(text: str) -> list[str]:
    """Extract one relative path per line or inline code span from a chat reply.

    This is intentionally conservative about prose. Safety and membership checks
    happen in ``select_paths`` so an unsafe requested path is rejected explicitly.
    """
    paths: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        value = line.strip()
        if re.match(r"^(?:`{3,}|~{3,})(?:[\w+-]*)\s*$", value):
            continue
        value = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+|>\s*)", "", value).strip()
        spans = [match[1] for match in re.findall(r"(`+)(.+?)\1", value)]
        values = spans if spans else [value]
        for item in values:
            item = item.strip()
            if not _looks_like_path(item):
                continue
            normalized = item.replace("\\", "/")
            while normalized.startswith("./"):
                normalized = normalized[2:]
            if normalized not in seen:
                paths.append(normalized)
                seen.add(normalized)
    return paths
