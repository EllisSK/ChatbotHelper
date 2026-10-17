"""Exercise complete file-upload workflows through the public CLI."""

import io
from pathlib import Path

import pytest

from chatbot_helper.cli import _check_fresh, main
from chatbot_helper.discovery import discover


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "sample project"
    (root / "src" / "shop").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "shop" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "shop" / "billing.py").write_bytes(
        b"from .helpers import clamp\r\n\r\ndef invoice(amount):\r\n    return clamp(amount)\r\n"
    )
    (root / "src" / "shop" / "helpers.py").write_text(
        "def clamp(value):\n    return max(0, value)\n", encoding="utf-8"
    )
    (root / "tests" / "test_billing.py").write_text(
        "from shop.billing import invoice\n\ndef test_invoice():\n    assert invoice(-1) == 0\n",
        encoding="utf-8",
    )
    (root / ".env").write_text("DO_NOT_EXPORT_THIS_CREDENTIAL", encoding="utf-8")
    (root / "README.md").write_text("A tiny invoicing example.\n", encoding="utf-8")
    return root


def test_task_export_contains_related_exact_source(project: Path, capsys):
    output = project / ".chatbot-helper" / "context.txt"
    code = main(["prepare", str(project), "--task", "Fix invoice", "--output", str(output)])
    assert code == 0
    exported = output.read_bytes().decode("utf-8")
    assert "src/shop/billing.py" in exported
    assert "src/shop/helpers.py" in exported
    assert "tests/test_billing.py" in exported
    assert (project / "src/shop/billing.py").read_bytes().decode("utf-8") in exported
    assert "DO_NOT_EXPORT_THIS_CREDENTIAL" not in exported
    assert str(project) not in exported
    assert "Upload this file" in capsys.readouterr().out


def test_overview_then_requested_windows_paths(project: Path):
    overview = project / ".chatbot-helper" / "overview.md"
    assert main(["overview", str(project), "-o", str(overview)]) == 0
    assert "invoice" in overview.read_text(encoding="utf-8")
    requests = project.parent / "requests.txt"
    requests.write_text(
        "Please provide these files:\n- `src\\shop\\billing.py`\n", encoding="utf-8"
    )
    output = project / ".chatbot-helper" / "requested.txt"
    assert main(["prepare", str(project), "--requests", str(requests), "-o", str(output)]) == 0
    assert "def invoice(amount):" in output.read_text(encoding="utf-8")


def test_explicit_oversize_file_fails_without_output(project: Path, capsys):
    output = project / ".chatbot-helper" / "too-small.txt"
    assert (
        main(
            [
                "prepare",
                str(project),
                "--include",
                "src/shop/billing.py",
                "--budget",
                "100",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()
    assert "Error:" in capsys.readouterr().err


def test_rejects_path_traversal(project: Path, capsys):
    assert main(["prepare", str(project), "--include", "../outside.py"]) == 2
    assert "Error:" in capsys.readouterr().err


def test_force_cannot_overwrite_source(project: Path):
    readme = project / "README.md"
    original = readme.read_bytes()
    assert main(["overview", str(project), "--output", str(readme), "--force"]) == 2
    assert readme.read_bytes() == original


def test_force_cannot_overwrite_ignored_project_file(project: Path):
    notes = project / "notes.md"
    notes.write_text("Keep these notes.", encoding="utf-8")
    (project / ".gitignore").write_text("notes.md\n", encoding="utf-8")
    assert main(["overview", str(project), "--output", str(notes), "--force"]) == 2
    assert notes.read_text(encoding="utf-8") == "Keep these notes."


def test_existing_export_requires_force(project: Path):
    output = project / ".chatbot-helper" / "overview.txt"
    arguments = ["overview", str(project), "--output", str(output)]
    assert main(arguments) == 0
    assert main(arguments) == 2
    assert main([*arguments, "--force"]) == 0


def test_additional_existing_output_is_included_without_execution(project: Path):
    evidence = project.parent / "tests-output.txt"
    evidence.write_text("FAILED test_invoice: expected 0, got -1", encoding="utf-8")
    output = project / ".chatbot-helper" / "evidence.txt"
    assert (
        main(
            [
                "prepare",
                str(project),
                "-i",
                "src/shop/billing.py",
                "--context",
                str(evidence),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert evidence.read_text() in output.read_text()


def test_source_changed_during_review_is_detected(project: Path):
    scan = discover(project)
    (project / "src/shop/helpers.py").write_text("changed = True\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed during preparation"):
        _check_fresh(scan, [])


def test_interactive_task_export(project: Path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("\n1\ndone\n\n\n"))
    assert main(["interactive", str(project), "--task", "Fix invoice"]) == 0
    outputs = list((project / ".chatbot-helper").glob("context-*.txt"))
    assert len(outputs) == 1
    assert "def invoice" in outputs[0].read_text()
    assert "Ready:" in capsys.readouterr().out


def test_interactive_nonpositive_budget_reprompts(project: Path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("\n1\ndone\n0\n\n\n"))
    assert main(["interactive", str(project), "--task", "Fix invoice"]) == 0
    assert "must be greater than zero" in capsys.readouterr().out


def test_interactive_requested_paths(project: Path, monkeypatch):
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO("\n3\nFix invoice\n```text\nsrc/shop/billing.py\n```\nEND\ndone\n\n\n"),
    )
    assert main(["interactive", str(project)]) == 0
    outputs = list((project / ".chatbot-helper").glob("context-*.txt"))
    assert len(outputs) == 1
    assert "def invoice" in outputs[0].read_text()


def test_help_without_terminal_does_not_wait_for_input(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert main([]) == 0
    assert "overview" in capsys.readouterr().out
