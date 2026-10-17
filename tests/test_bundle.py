from __future__ import annotations

import re

import pytest

from chatbot_helper.bundle import BudgetError, build_bundle, build_overview
from chatbot_helper.discovery import SourceFile
from chatbot_helper.python_context import analyse
from chatbot_helper.selection import Candidate


def sources(**contents: str) -> dict[str, SourceFile]:
    return {
        path: SourceFile(path, content, len(content.encode())) for path, content in contents.items()
    }


def test_source_preserved_with_embedded_fences_crlf_and_no_final_newline() -> None:
    original = 'value = "```quoted```"\r\n# café\r\nprint(value)'
    files = sources(**{"src/example.py": original})
    result = build_bundle(
        files,
        analyse(files),
        [Candidate("src/example.py", 1, ("selected",), pinned=True)],
        task="Explain the output",
    )
    assert f"````python\n{original}\n````" in result.content
    assert "final newline: absent" in result.content
    assert result.included == ("src/example.py",)
    assert result.omitted == {}
    assert result.characters == len(result.content)
    assert result.estimated_tokens == (result.characters + 3) // 4


def test_hard_budget_skips_whole_unpinned_file_and_preserves_reason() -> None:
    files = sources(**{"small.py": "answer = 42\n", "large.py": "# lots of source\n" * 500})
    result = build_bundle(
        files,
        analyse(files),
        [Candidate("small.py", 2, ()), Candidate("large.py", 1, ())],
        task="Inspect answer",
        budget=1600,
    )
    assert result.characters <= 1600
    assert result.included == ("small.py",)
    assert result.omitted == {"large.py": "Exceeds the character budget."}
    assert "# lots of source" not in result.content
    assert "over budget" in result.content


def test_pinned_oversized_source_raises_instead_of_truncating() -> None:
    files = sources(**{"large.py": "x = 1\n" * 1000})
    with pytest.raises(BudgetError, match="Pinned file 'large.py'.*Remove a selected file"):
        build_bundle(
            files,
            analyse(files),
            [Candidate("large.py", 0, (), pinned=True)],
            task="Inspect",
            budget=1600,
        )


def test_pinned_source_is_prioritized_even_if_unpinned_comes_first() -> None:
    files = sources(**{"small.py": "x = 1\n", "large.py": "# lots of source\n" * 500})
    result = build_bundle(
        files,
        analyse(files),
        [Candidate("large.py", 10, ()), Candidate("small.py", 1, (), pinned=True)],
        task="Inspect",
        budget=1600,
    )
    assert result.included == ("small.py",)


def test_omission_report_compacts_with_complete_metadata_for_many_files() -> None:
    files = sources(**{f"long_directory_name/file_{i:03d}.py": "x = 1\n" for i in range(100)})
    excluded = {f"ignored/folder_{i}/": "ignored by .gitignore" for i in range(100)}
    result = build_bundle(files, analyse(files), [], task="Review", budget=1300, excluded=excluded)
    assert result.characters <= 1300
    assert len(result.omitted) == 200
    assert "100 excluded" in result.content
    assert "Individual paths shown:" in result.content


def test_overview_is_navigation_and_does_not_contain_function_bodies() -> None:
    files = sources(**{"app.py": "def run(name: str):\n    return 'body-only-marker'\n"})
    result = build_overview(files, analyse(files), task="Understand run")
    assert "def run(name: str)" in result.content
    assert "body-only-marker" not in result.content
    assert "navigation only" in result.content.lower()
    assert result.included == ("app.py",)


def test_overview_budget_does_not_silently_clip_map_entries() -> None:
    files = sources(
        **{f"pkg/module_{i}.py": f"def operation_{i}():\n    pass\n" for i in range(60)}
    )
    result = build_overview(files, analyse(files), budget=1400)
    assert result.characters <= 1400
    assert result.omitted
    assert set(result.included).isdisjoint(result.omitted)
    assert set(result.included) | set(result.omitted) == set(files)
    for path in result.included:
        assert f"- {path} (" in result.content


def test_exclusions_are_reported_and_never_exported_even_if_present_in_files() -> None:
    files = sources(**{"safe.py": "x = 1\n", "hidden/private.py": "never-export-marker"})
    excluded = {"hidden/": "explicit exclusion"}
    result = build_overview(files, analyse(files), excluded=excluded)
    assert "never-export-marker" not in result.content
    assert "hidden/private.py" not in result.content
    assert result.included == ("safe.py",)
    assert result.omitted == {"hidden/": "Excluded: explicit exclusion"}
    with pytest.raises(ValueError, match="No available files"):
        build_bundle(
            files,
            analyse(files),
            [Candidate("hidden/private.py", 1, (), pinned=True)],
            task="Inspect",
            excluded=excluded,
        )


def test_additional_context_is_exact_and_mandatory() -> None:
    context = "Traceback:\r\nerror: unexpected `value`"
    result = build_bundle(
        {}, {}, [], task="Debug", extra_context={"Test output": context}, format="txt"
    )
    assert context in result.content
    assert "ADDITIONAL CONTEXT: TEST OUTPUT" in result.content
    with pytest.raises(BudgetError, match="required additional context"):
        build_bundle({}, {}, [], task="Debug", extra_context={"Log": "x" * 3000}, budget=1500)


@pytest.mark.parametrize("budget", [0, -1, True])
def test_invalid_budgets_are_rejected(budget: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        build_overview({}, {}, budget=budget)


def test_timestamp_uses_explicit_utc_offset_and_no_local_root_path() -> None:
    result = build_bundle({}, {}, [], task="Inspect")
    assert re.search(r"Generated \(UTC\): \d{4}-\d{2}-\d{2}T.*\+00:00", result.content)
    assert "/Users/" not in result.content
