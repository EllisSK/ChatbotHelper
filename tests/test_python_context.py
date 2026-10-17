from chatbot_helper.discovery import SourceFile
from chatbot_helper.python_context import analyse, dependencies


def sources(contents: dict[str, str]) -> dict[str, SourceFile]:
    return {
        path: SourceFile(path=path, content=content, size_bytes=len(content.encode()))
        for path, content in contents.items()
    }


def test_source_index_contains_signatures_and_class_methods_without_execution() -> None:
    modules = analyse(
        sources(
            {
                "app.py": """raise RuntimeError('must not execute')
import os
from external.package import Widget

def greet(name: str, *, loud: bool = False) -> str:
    return name

class Greeter(object):
    async def greet(self, name: str) -> str:
        return name
"""
            }
        )
    )

    module = modules["app.py"]
    assert module.parse_error is None
    assert module.module_name == "app"
    assert module.imports == ("os", "external.package.Widget")
    assert [(symbol.name, symbol.kind) for symbol in module.symbols] == [
        ("greet", "function"),
        ("Greeter", "class"),
        ("Greeter.greet", "method"),
    ]
    assert module.symbols[0].signature == "def greet(name: str, *, loud: bool=False) -> str"
    assert module.symbols[-1].signature == "async def Greeter.greet(self, name: str) -> str"
    assert module.symbols[0].line == 5
    assert module.symbols[0].end_line == 6


def test_src_layout_relative_imports_and_package_initializers() -> None:
    modules = analyse(
        sources(
            {
                "src/project/__init__.py": "from . import helpers\n",
                "src/project/helpers.py": "import json\n",
                "src/project/core/__init__.py": "",
                "src/project/core/main.py": (
                    "from ..helpers import work\nfrom . import local\nfrom project import helpers\n"
                ),
                "src/project/core/local.py": "from .. import helpers\n",
                "tests/test_main.py": "from project.core.main import run\n",
            }
        )
    )

    graph = dependencies(modules)

    assert modules["src/project/core/main.py"].module_name == "project.core.main"
    assert graph["src/project/core/main.py"] == {
        "src/project/__init__.py",
        "src/project/helpers.py",
        "src/project/core/__init__.py",
        "src/project/core/local.py",
    }
    assert graph["src/project/__init__.py"] == {"src/project/helpers.py"}
    assert graph["tests/test_main.py"] == {
        "src/project/__init__.py",
        "src/project/core/__init__.py",
        "src/project/core/main.py",
    }


def test_plain_layout_namespace_packages_and_stub_files() -> None:
    modules = analyse(
        sources(
            {
                "package/main.py": "import package.helpers\nfrom external import thing\n",
                "package/helpers.py": "",
                "package/helpers.pyi": "def work() -> None: ...\n",
                "README.md": "not Python",
            }
        )
    )

    assert "README.md" not in modules
    assert dependencies(modules)["package/main.py"] == {"package/helpers.py", "package/helpers.pyi"}


def test_wildcard_import_resolves_package_and_ignores_invalid_relative_import() -> None:
    modules = analyse(
        sources(
            {
                "pkg/__init__.py": "",
                "pkg/main.py": "from . import *\nfrom ... import invalid\n",
                "script.py": "from . import invalid\n",
                "invalid.py": "",
            }
        )
    )

    graph = dependencies(modules)

    assert graph["pkg/main.py"] == {"pkg/__init__.py"}
    assert graph["script.py"] == set()


def test_syntax_errors_degrade_gracefully_and_other_files_still_index() -> None:
    modules = analyse(
        sources(
            {
                "broken.py": "def broken(:\n",
                "okay.py": "def okay():\n    return 1\n",
            }
        )
    )

    assert modules["broken.py"].parse_error
    assert "line 1" in modules["broken.py"].parse_error
    assert modules["broken.py"].symbols == ()
    assert modules["okay.py"].symbols[0].name == "okay"


def test_signatures_are_bounded_for_large_defaults() -> None:
    modules = analyse(sources({"long.py": f"def long(value={'x' * 1000!r}): pass\n"}))

    assert len(modules["long.py"].symbols[0].signature) == 180
    assert modules["long.py"].symbols[0].signature.endswith("…")


def test_dependency_graph_contains_only_direct_edges_and_no_self_edges() -> None:
    modules = analyse(
        sources(
            {
                "one.py": "import two\nimport one\n",
                "two.py": "import three\n",
                "three.py": "",
            }
        )
    )

    assert dependencies(modules) == {
        "one.py": {"two.py"},
        "two.py": {"three.py"},
        "three.py": set(),
    }


def test_function_local_imports_and_nested_class_methods_are_indexed() -> None:
    modules = analyse(
        sources(
            {
                "main.py": """class Outer:
    class Inner:
        def work(self):
            import helper
""",
                "helper.py": "",
            }
        )
    )

    assert dependencies(modules)["main.py"] == {"helper.py"}
    assert [symbol.name for symbol in modules["main.py"].symbols] == [
        "Outer",
        "Outer.Inner",
        "Outer.Inner.work",
    ]
