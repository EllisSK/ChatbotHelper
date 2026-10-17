from __future__ import annotations

import pytest

from chatbot_helper.discovery import SourceFile
from chatbot_helper.python_context import analyse
from chatbot_helper.selection import parse_requests, select_paths, suggest


def sources(**contents: str) -> dict[str, SourceFile]:
    return {
        path: SourceFile(path, content, len(content.encode())) for path, content in contents.items()
    }


def test_recommendations_explain_dependencies_and_tests_without_recursive_expansion() -> None:
    files = sources(
        **{
            "src/pkg/login.py": "from .store import save\ndef authenticate():\n    save()\n",
            "src/pkg/store.py": "from .database import connect\ndef save():\n    connect()\n",
            "src/pkg/database.py": "def connect():\n    pass\n",
            "tests/test_login.py": "from pkg.login import authenticate\n",
            "unrelated.py": "value = 1\n",
        }
    )
    candidates = suggest(files, analyse(files), "", pinned=["src/pkg/login.py"])
    by_path = {candidate.path: candidate for candidate in candidates}
    assert candidates[0].path == "src/pkg/login.py"
    assert candidates[0].pinned and candidates[0].score > 0
    assert "Imported by src/pkg/login.py" in by_path["src/pkg/store.py"].reasons
    assert "Related tests for src/pkg/login.py" in by_path["tests/test_login.py"].reasons
    assert by_path["src/pkg/database.py"].score == 0
    assert by_path["unrelated.py"].score == 0


def test_task_matches_symbols_and_ties_are_deterministic() -> None:
    files = sources(
        **{
            "z.py": "def retry_connection():\n    pass\n",
            "a.py": "def retry_connection():\n    pass\n",
            "b.py": "value = 1\n",
        }
    )
    candidates = suggest(files, analyse(files), "Improve retry connection")
    assert [candidate.path for candidate in candidates] == ["a.py", "z.py", "b.py"]
    assert "Symbols match: connection, retry" in candidates[0].reasons
    reverse = dict(reversed(list(files.items())))
    assert suggest(reverse, analyse(reverse), "Improve retry connection") == candidates


def test_explicit_windows_paths_and_recursive_globs() -> None:
    files = sources(
        **{
            "src/main.py": "",
            "src/pkg/helper.py": "",
            "src/pkg/docs/readme.md": "",
            "root.py": "",
        }
    )
    assert select_paths(files, [r".\src\main.py", "src/**/*.py", "root.py"]) == [
        "src/main.py",
        "src/pkg/helper.py",
        "root.py",
    ]
    assert select_paths(files, ["**/*.py"]) == [
        "root.py",
        "src/main.py",
        "src/pkg/helper.py",
    ]
    assert select_paths(files, ["src/*.py"]) == ["src/main.py"]


@pytest.mark.parametrize(
    "path", ["../secret.py", "src/../../x.py", "/etc/x.py", r"C:\x.py", r"\\server\x.py", "C:x.py"]
)
def test_requested_paths_cannot_escape_the_project(path: str) -> None:
    with pytest.raises(ValueError, match="relative to the project root"):
        select_paths(sources(**{"ok.py": ""}), [path])


def test_missing_or_excluded_requested_file_has_actionable_error() -> None:
    with pytest.raises(ValueError, match="excluded files cannot be selected"):
        select_paths(sources(**{"ok.py": ""}), ["missing.py"])


def test_chat_request_extraction_handles_markdown_and_spaces_without_prose() -> None:
    text = """Please provide the following files:
- `src/main.py` to inspect the command.
2. `src/my helpers.py`
```text
.\\src\\main.py
tests/test_main.py
```
README.md
Please inspect src/other.py
Here are the files:
"""
    assert parse_requests(text) == [
        "src/main.py",
        "src/my helpers.py",
        "tests/test_main.py",
        "README.md",
    ]


def test_unsafe_chat_request_is_extracted_then_rejected() -> None:
    requests = parse_requests("- `../private.py`\n- `C:\\private.py`")
    assert requests == ["../private.py", "C:/private.py"]
    with pytest.raises(ValueError, match="Unsafe path"):
        select_paths({}, requests)
