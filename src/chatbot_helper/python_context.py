"""A small static Python index for context selection and repository maps."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from chatbot_helper.discovery import SourceFile


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    signature: str
    line: int
    end_line: int


@dataclass(frozen=True)
class PythonModule:
    path: str
    module_name: str
    imports: tuple[str, ...]
    symbols: tuple[Symbol, ...]
    parse_error: str | None


def _module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _compact(text: str, limit: int = 180) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _symbols(tree: ast.Module) -> tuple[Symbol, ...]:
    symbols: list[Symbol] = []

    def add(node: ast.AST, prefix: str = "") -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = f"{prefix}{node.name}"
            qualifier = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
            signature = f"{qualifier}def {name}({ast.unparse(node.args)})"
            if node.returns:
                signature += f" -> {ast.unparse(node.returns)}"
            kind = "method" if prefix else "function"
        elif isinstance(node, ast.ClassDef):
            name = f"{prefix}{node.name}"
            bases = [ast.unparse(base) for base in node.bases]
            bases.extend(ast.unparse(keyword) for keyword in node.keywords)
            signature = f"class {name}" + (f"({', '.join(bases)})" if bases else "")
            kind = "class"
        else:
            return
        symbols.append(
            Symbol(
                name=name,
                kind=kind,
                signature=_compact(signature),
                line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            )
        )
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                add(child, f"{name}.")

    for node in tree.body:
        add(node)
    return tuple(symbols)


def analyse(files: Mapping[str, SourceFile]) -> dict[str, PythonModule]:
    """Index imports and signatures without importing or executing source.

    ``from package import name`` is represented as ``package.name``. Import
    resolution later finds the longest local module prefix and package parents.
    """
    modules: dict[str, PythonModule] = {}
    for path, source in sorted(files.items()):
        if PurePosixPath(path).suffix.casefold() not in {".py", ".pyi"}:
            continue
        module_name = _module_name(path)
        try:
            tree = ast.parse(source.content, filename=path)
            imports: dict[str, None] = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports[alias.name] = None
                elif isinstance(node, ast.ImportFrom):
                    base = "." * node.level + (node.module or "")
                    for alias in node.names:
                        if alias.name == "*":
                            imported = base
                        else:
                            separator = "" if not node.module else "."
                            imported = f"{base}{separator}{alias.name}"
                        imports[imported] = None
            modules[path] = PythonModule(
                path=path,
                module_name=module_name,
                imports=tuple(imports),
                symbols=_symbols(tree),
                parse_error=None,
            )
        except (SyntaxError, ValueError, RecursionError) as exc:
            if isinstance(exc, SyntaxError):
                error = f"{exc.msg} (line {exc.lineno or '?'})"
            else:
                error = str(exc)
            modules[path] = PythonModule(path, module_name, (), (), error)
    return modules


def dependencies(modules: Mapping[str, PythonModule]) -> dict[str, set[str]]:
    """Resolve direct local imports, including parent package initializers."""
    by_name: dict[str, set[str]] = {}
    for path, module in modules.items():
        by_name.setdefault(module.module_name, set()).add(path)
    graph: dict[str, set[str]] = {path: set() for path in modules}
    for path, module in modules.items():
        package = (
            module.module_name
            if PurePosixPath(path).stem == "__init__"
            else module.module_name.rpartition(".")[0]
        )
        for imported in module.imports:
            level = len(imported) - len(imported.lstrip("."))
            if level:
                package_parts = package.split(".") if package else []
                if level > len(package_parts):
                    continue
                base = package_parts[: len(package_parts) - level + 1]
                suffix = imported[level:]
                qualified = ".".join([*base, *([suffix] if suffix else [])])
            else:
                qualified = imported
            parts = qualified.split(".")
            for count in range(1, len(parts) + 1):
                graph[path].update(by_name.get(".".join(parts[:count]), ()))
        graph[path].discard(path)
    return graph
