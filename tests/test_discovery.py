from pathlib import Path

import pytest

from chatbot_helper.discovery import discover


def write(root: Path, path: str, content: str = "pass\n") -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def test_nested_ignore_files_and_negation(tmp_path: Path) -> None:
    write(tmp_path, ".gitignore", "*.py\n!keep.py\n!package/\n")
    write(tmp_path, "keep.py")
    write(tmp_path, "discard.py")
    write(tmp_path, "package/.gitignore", "!inside.py\n")
    write(tmp_path, "package/inside.py")
    write(tmp_path, "package/discard.py")

    result = discover(tmp_path)

    assert set(result.files) == {"keep.py", "package/inside.py"}
    assert result.excluded["discard.py"] == "ignored by .gitignore"
    assert result.excluded["package/discard.py"] == "ignored by .gitignore"


def test_ignored_parent_directory_cannot_be_reincluded_by_child_rule(tmp_path: Path) -> None:
    write(tmp_path, ".gitignore", "hidden/\n!hidden/keep.py\n")
    write(tmp_path, "hidden/.gitignore", "!keep.py\n")
    write(tmp_path, "hidden/keep.py")

    result = discover(tmp_path)

    assert not result.files
    assert result.excluded["hidden/"] == "ignored by .gitignore"
    assert "hidden/keep.py" not in result.excluded


def test_directory_negation_allows_selected_children(tmp_path: Path) -> None:
    write(tmp_path, ".gitignore", "generated/*\n!generated/keep.py\n")
    write(tmp_path, "generated/keep.py")
    write(tmp_path, "generated/other.py")

    assert set(discover(tmp_path).files) == {"generated/keep.py"}


def test_nested_helper_ignores_and_independent_git_rules(tmp_path: Path) -> None:
    write(tmp_path, ".gitignore", "git_excluded.py\n")
    write(tmp_path, ".chatbothelperignore", "*.md\n!git_excluded.py\n")
    write(tmp_path, "git_excluded.py")
    write(tmp_path, "root.md")
    write(tmp_path, "nested/.chatbothelperignore", "!guide.md\n")
    write(tmp_path, "nested/guide.md")

    result = discover(tmp_path)

    assert set(result.files) == {"nested/guide.md"}
    assert result.excluded["git_excluded.py"] == "ignored by .gitignore"
    assert result.excluded["root.md"] == "ignored by .chatbothelperignore"


def test_sensitive_files_and_generated_directories_are_excluded(tmp_path: Path) -> None:
    for path in (
        ".env",
        ".env.example",
        "credentials.json",
        "secrets.toml",
        "private.key",
        "service-account-example.json",
        ".aws/credentials",
        ".ssh/config",
        ".venv/library.py",
        "module.egg-info/info.txt",
        ".chatbot-helper/context.md",
        "build/generated.py",
        "node_modules/library.py",
    ):
        write(tmp_path, path)
    write(tmp_path, ".gitignore", "!*\n")
    write(tmp_path, "main.py")

    result = discover(tmp_path)

    assert set(result.files) == {"main.py"}
    assert result.excluded[".env.example"] == "possible credential file or directory"
    assert result.excluded[".aws/"] == "credential directory"
    assert result.excluded[".chatbot-helper/"] == "default excluded directory"


def test_python_coding_cookie_bom_and_source_newlines_are_preserved(tmp_path: Path) -> None:
    python = b"# coding: latin-1\r\nname = 'caf\xe9'\r\n"
    (tmp_path / "legacy.py").write_bytes(python)
    (tmp_path / "notes.md").write_bytes(b"\xef\xbb\xbfNotes\r\n")

    result = discover(tmp_path)

    assert result.files["legacy.py"].content == "# coding: latin-1\r\nname = 'café'\r\n"
    assert result.files["legacy.py"].size_bytes == len(python)
    assert result.files["notes.md"].content == "Notes\r\n"


def test_invalid_encoding_binary_and_size_limits_are_reported(tmp_path: Path) -> None:
    (tmp_path / "binary.txt").write_bytes(b"a\0b")
    (tmp_path / "bad.txt").write_bytes(b"\xff")
    (tmp_path / "wrong.py").write_bytes(b"# coding: missing-codec\npass\n")
    write(tmp_path, "large.py", "x" * 101)
    write(tmp_path, "okay.py", "pass\n")

    result = discover(tmp_path, max_file_bytes=100)

    assert set(result.files) == {"okay.py"}
    assert result.excluded["binary.txt"] == "binary content"
    assert result.excluded["bad.txt"] == "undecodable text"
    assert result.excluded["wrong.py"] == "undecodable text"
    assert result.excluded["large.py"] == "exceeds 100 byte file limit"
    assert len(result.warnings) == 2


def test_symlink_files_and_directories_are_never_followed(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    external = write(tmp_path, "outside/private.py", "SECRET = 'outside'\n")
    try:
        (root / "linked.py").symlink_to(external)
        (root / "linked-dir").symlink_to(external.parent, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("Creating symlinks requires permissions on this platform")

    result = discover(root)

    assert not result.files
    assert result.excluded["linked.py"] == "symbolic link"
    assert result.excluded["linked-dir"] == "symbolic link"


def test_junctions_are_excluded_before_loading_ignores_or_traversing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    junction = tmp_path / "junction"
    write(tmp_path, "junction/.gitignore", "*.py\n")
    write(tmp_path, "junction/outside.py")
    write(tmp_path, "main.py")
    original_is_junction = Path.is_junction
    original_read_text = Path.read_text
    original_iterdir = Path.iterdir

    def is_junction(path: Path) -> bool:
        return path == junction or original_is_junction(path)

    def read_text(path: Path, *args, **kwargs):
        assert path.parent != junction, "junction ignore files must not be read"
        return original_read_text(path, *args, **kwargs)

    def iterdir(path: Path):
        assert path != junction, "junction directories must not be traversed"
        return original_iterdir(path)

    # Simulate the Windows junction predicate on every test platform.
    monkeypatch.setattr(Path, "is_junction", is_junction)
    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "iterdir", iterdir)

    result = discover(tmp_path)

    assert set(result.files) == {"main.py"}
    assert result.excluded["junction/"] == "directory junction"
    assert "junction/outside.py" not in result.excluded


def test_supported_file_types_and_relative_posix_paths(tmp_path: Path) -> None:
    for path in ("README", "LICENSE", "Dockerfile", "Makefile", "pkg/module.pyi", "config.yaml"):
        write(tmp_path, path)
    write(tmp_path, "photo.png")

    result = discover(tmp_path)

    assert set(result.files) == {
        "README",
        "LICENSE",
        "Dockerfile",
        "Makefile",
        "pkg/module.pyi",
        "config.yaml",
    }
    assert result.files["pkg/module.pyi"].path == "pkg/module.pyi"
    assert result.excluded["photo.png"] == "unsupported file type"
    assert result.root == tmp_path.resolve()


def test_configured_exclusions_support_negation(tmp_path: Path) -> None:
    write(tmp_path, "keep.py")
    write(tmp_path, "omit.py")

    result = discover(tmp_path, excludes=["*.py", "!keep.py"])

    assert set(result.files) == {"keep.py"}
    assert result.excluded["omit.py"] == "ignored by configured exclusions"


def test_invalid_root_and_size_limit_fail_clearly(tmp_path: Path) -> None:
    file = write(tmp_path, "file.py")
    with pytest.raises(ValueError, match="not a directory"):
        discover(file)
    with pytest.raises(ValueError, match="must be positive"):
        discover(tmp_path, max_file_bytes=0)


def test_invalid_ignore_file_is_reported_without_losing_readable_source(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_bytes(b"\xff")
    write(tmp_path, "main.py")

    result = discover(tmp_path)

    assert set(result.files) == {"main.py"}
    assert any("Could not read ignore rules" in warning for warning in result.warnings)
