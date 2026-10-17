"""Interactive and scriptable context exports. All project processing is local."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from rich import box
from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from chatbot_helper import __version__
from chatbot_helper.bundle import BudgetError, BundleResult, build_bundle, build_overview
from chatbot_helper.discovery import DiscoveryResult, discover
from chatbot_helper.python_context import PythonModule, analyse
from chatbot_helper.selection import Candidate, parse_requests, select_paths, suggest

DEFAULT_BUDGET = 60_000


def _positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="chatbot-helper",
        description="Prepare local Python project context for manual upload to a coding chat.",
    )
    result.add_argument("--version", action="version", version=f"ChatbotHelper {__version__}")
    commands = result.add_subparsers(dest="command")
    for name, help_text in (
        ("interactive", "Choose a project, review files, and export interactively."),
        ("overview", "Export a project map so a chat can request relevant files."),
        ("prepare", "Export source selected by task, patterns, or a chat's file request."),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("project", nargs="?", type=Path, default=Path.cwd())
        command.add_argument("--output", "-o", type=Path, help="Destination .txt or .md file.")
        command.add_argument(
            "--format", choices=("txt", "md"), help="Default: txt, or output suffix."
        )
        command.add_argument(
            "--budget", type=_positive, default=DEFAULT_BUDGET, help="Maximum export characters."
        )
        command.add_argument(
            "--exclude", action="append", default=[], metavar="PATTERN", help="Extra ignore rule."
        )
        command.add_argument("--task", default="", help="Task and constraints to give the chat.")
        command.add_argument("--task-file", type=Path, help="Read a longer task from a UTF-8 file.")
        command.add_argument("--force", action="store_true", help="Replace an existing export.")
        if name != "overview":
            command.add_argument(
                "--include",
                "-i",
                action="append",
                default=[],
                metavar="PATH_OR_GLOB",
                help="Pin a relative file or glob; repeat for multiple patterns.",
            )
            command.add_argument(
                "--requests", type=Path, help="Read a chat's requested relative paths from a file."
            )
            command.add_argument(
                "--context",
                action="append",
                default=[],
                type=Path,
                metavar="FILE",
                help="Include existing traceback, test output, or diff; no commands are run.",
            )
    return result


def _text_file(path: Path) -> str:
    if path.stat().st_size > 200_000:
        raise ValueError(f"Context file is larger than 200,000 bytes: {path}")
    return path.read_bytes().decode("utf-8-sig")


def _load(
    args: argparse.Namespace, console: Console
) -> tuple[DiscoveryResult, dict[str, PythonModule]]:
    scan = discover(args.project.expanduser(), excludes=args.exclude)
    console.print(f"Found {len(scan.files)} readable files; {len(scan.excluded)} exclusions.")
    for warning in scan.warnings:
        console.print(f"Scan warning: {warning}")
    if not scan.files:
        raise ValueError("No supported files found. Check the project path and ignore rules.")
    return scan, analyse(scan.files)


def _task(args: argparse.Namespace) -> str:
    parts = [args.task]
    if args.task_file:
        parts.append(_text_file(args.task_file))
    return "\n\n".join(part.strip() for part in parts if part.strip())


def _pins(args: argparse.Namespace, scan: DiscoveryResult) -> list[str]:
    patterns = list(args.include)
    if args.requests:
        requests = parse_requests(_text_file(args.requests))
        if not requests:
            raise ValueError("No relative file paths found in the requests file.")
        patterns.extend(requests)
    return select_paths(scan.files, patterns) if patterns else []


def _evidence(paths: Sequence[Path]) -> dict[str, str]:
    return {f"{index}. {path.name}": _text_file(path) for index, path in enumerate(paths, 1)}


def _output(args: argparse.Namespace, root: Path, mode: str) -> tuple[Path, str]:
    output = args.output.expanduser() if args.output else None
    suffix = output.suffix.lower().lstrip(".") if output else ""
    format_name = args.format or (suffix if suffix in ("txt", "md") else "txt")
    if output is None:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        output = root / ".chatbot-helper" / f"{mode}-{stamp}.{format_name}"
    elif suffix != format_name:
        raise ValueError("Output must have a .txt or .md suffix matching --format.")
    return output, format_name


def _check_fresh(scan: DiscoveryResult, excludes: Sequence[str]) -> None:
    fresh = discover(scan.root, excludes=excludes)
    if scan.files != fresh.files or scan.excluded != fresh.excluded:
        raise ValueError(
            "Project files changed during preparation. Run again to use current source."
        )


def _write(path: Path, result: BundleResult, scan: DiscoveryResult, *, force: bool) -> None:
    if path.is_dir():
        raise ValueError("The export destination must be a file, not a directory.")
    if path.is_symlink():
        raise ValueError("The export destination must not be a symbolic link.")
    resolved = path.resolve()
    if resolved.is_relative_to(scan.root):
        relative = resolved.relative_to(scan.root).as_posix()
        if relative in scan.files or (
            path.exists() and resolved.relative_to(scan.root).parts[0] != ".chatbot-helper"
        ):
            raise ValueError(
                "Existing project files cannot be export destinations. "
                "Use .chatbot-helper/ or a path outside the project."
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w" if force else "x", encoding="utf-8", newline="") as stream:
        stream.write(result.content)


def _summary(result: BundleResult, output: Path, console: Console) -> None:
    console.print(f"Exported: {output.resolve()}", soft_wrap=True)
    console.print(
        f"{len(result.included)} files represented; {result.characters:,} characters; "
        f"about {result.estimated_tokens:,} tokens."
    )
    console.print("Token count is a rough estimate, not the chat's remaining capacity.")
    if result.omitted:
        console.print(f"{len(result.omitted)} omissions. See the export's omission report.")
    console.print("Upload this file to your chat and include your task in the message.")


def _numbers(value: str, count: int) -> set[int]:
    selected: set[int] = set()
    for part in value.split(","):
        bounds = part.strip().split("-")
        if len(bounds) == 1:
            selected.add(int(bounds[0]))
        elif len(bounds) == 2:
            first, last = map(int, bounds)
            if first > last:
                raise ValueError("Ranges must be ascending.")
            if last - first > count:
                raise ValueError("Range exceeds the file list.")
            selected.update(range(first, last + 1))
        else:
            raise ValueError("Use file numbers such as 1,3-5.")
    if any(number < 1 or number > count for number in selected):
        raise ValueError(f"File numbers must be between 1 and {count}.")
    return selected


def _review(
    candidates: list[Candidate], scan: DiscoveryResult, selected: set[str], console: Console
) -> set[str]:
    while True:
        table = Table("#", "Use", "File", "Chars", "Reason", box=box.SIMPLE, safe_box=True)
        for index, candidate in enumerate(candidates, 1):
            table.add_row(
                str(index),
                "yes" if candidate.path in selected else "",
                Text(candidate.path),
                f"{len(scan.files[candidate.path].content):,}",
                Text("; ".join(candidate.reasons) or "manual selection"),
            )
        console.print(table)
        console.print(
            "Enter numbers/ranges to replace selection (1,3-5), 'add PATH_OR_GLOB', "
            "'remove PATH_OR_GLOB', 'show NUMBER', 'all', 'none', or 'done'."
        )
        console.print(f"Currently selected: {len(selected)} files.")
        choice = Prompt.ask("Selection", default="done", console=console).strip()
        try:
            if choice.lower() == "done":
                if selected:
                    return selected
                console.print("Select at least one file, or press Ctrl+C to cancel.")
            elif choice.lower() == "all":
                selected = set(scan.files)
            elif choice.lower() == "none":
                selected = set()
            elif choice.startswith(("add ", "remove ")):
                operation, pattern = choice.split(" ", 1)
                matches = select_paths(scan.files, [pattern.strip().strip('"').strip("'")])
                if operation == "add":
                    selected.update(matches)
                else:
                    selected.difference_update(matches)
            elif choice.startswith("show "):
                number = int(choice[5:].strip())
                if number < 1 or number > len(candidates):
                    raise ValueError("Choose a number from the file list.")
                file = scan.files[candidates[number - 1].path]
                console.print(Text(f"--- {file.path} ---"))
                lines = file.content.splitlines()
                for line_number, line in enumerate(lines[:80], 1):
                    console.print(Text(f"{line_number:4} | {line}"))
                if len(lines) > 80:
                    console.print(
                        f"Showing 80 of {len(lines)} lines; exports contain the full file."
                    )
            else:
                selected = {
                    candidates[number - 1].path for number in _numbers(choice, len(candidates))
                }
        except ValueError as error:
            console.print(f"Selection error: {error}")


def _request_paste(console: Console) -> str:
    console.print("Paste Copilot's requested relative paths. Finish with a line containing END.")
    lines: list[str] = []
    while True:
        line = console.input()
        if line.strip() == "END":
            return "\n".join(lines)
        lines.append(line)


def _interactive(args: argparse.Namespace, console: Console) -> int:
    console.print("ChatbotHelper - prepare context for file upload")
    project = Prompt.ask("Project folder", default=str(args.project), console=console)
    args.project = Path(project.strip().strip('"')).expanduser()
    console.print("1. Task-based source bundle\n2. Project overview\n3. Files requested by Copilot")
    mode = Prompt.ask("Workflow", choices=["1", "2", "3"], default="1", console=console)
    task = _task(args)
    if not task:
        task = Prompt.ask(
            "Task and constraints (optional for overview)", default="", console=console
        )
    if mode == "1":
        while not task.strip():
            task = Prompt.ask("Describe the task", console=console)
    scan, modules = _load(args, console)
    pins = _pins(args, scan)
    if mode == "3" and not args.requests:
        requests = parse_requests(_request_paste(console))
        if not requests:
            raise ValueError("No relative file paths found. Copy the requested paths from Copilot.")
        pins = sorted(set(pins) | set(select_paths(scan.files, requests)))
    candidates = suggest(scan.files, modules, task if mode == "1" else "", pinned=pins)
    selected = {
        candidate.path for candidate in candidates if candidate.score > 0 or candidate.pinned
    }
    if mode != "2":
        selected = _review(candidates, scan, selected, console)
    else:
        console.print(
            "The overview lists paths and Python definitions; it contains no full sources."
        )
    while True:
        args.budget = IntPrompt.ask(
            "Maximum export characters", default=args.budget, console=console
        )
        if args.budget > 0:
            break
        console.print("The character budget must be greater than zero.")
        args.budget = DEFAULT_BUDGET
    output, format_name = _output(args, scan.root, "overview" if mode == "2" else "context")
    extra_context = _evidence(args.context)
    while True:
        try:
            if mode == "2":
                result = build_overview(
                    scan.files,
                    modules,
                    task=task,
                    budget=args.budget,
                    format=format_name,
                    excluded=scan.excluded,
                )
            else:
                reviewed = [
                    Candidate(candidate.path, candidate.score, candidate.reasons, pinned=True)
                    for candidate in candidates
                    if candidate.path in selected
                ]
                result = build_bundle(
                    scan.files,
                    modules,
                    reviewed,
                    task=task,
                    budget=args.budget,
                    format=format_name,
                    extra_context=extra_context,
                    excluded=scan.excluded,
                )
            break
        except BudgetError as error:
            console.print(f"Budget: {error}")
            value = IntPrompt.ask("New character budget (0 to revise selection)", console=console)
            if value == 0 and mode != "2":
                selected = _review(candidates, scan, selected, console)
            elif value > 0:
                args.budget = value
    console.print(
        f"Ready: {result.characters:,} characters; {len(result.included)} files represented; "
        f"{len(result.omitted)} omissions."
    )
    if not Confirm.ask("Write the upload file?", default=True, console=console):
        console.print("Export cancelled.")
        return 0
    force = args.force
    if output.exists() and not force:
        force = Confirm.ask(f"Replace existing export {output}?", default=False, console=console)
        if not force:
            console.print("Export cancelled.")
            return 0
    _check_fresh(scan, args.exclude)
    _write(output, result, scan, force=force)
    _summary(result, output, console)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    if args.command is None:
        if not sys.stdin.isatty():
            argument_parser.print_help()
            return 0
        args = argument_parser.parse_args(["interactive"])
    console = Console(markup=False, highlight=False)
    try:
        if args.command == "interactive":
            return _interactive(args, console)
        task = _task(args)
        scan, modules = _load(args, console)
        output, format_name = _output(args, scan.root, args.command)
        if args.command == "overview":
            result = build_overview(
                scan.files,
                modules,
                task=task,
                budget=args.budget,
                format=format_name,
                excluded=scan.excluded,
            )
        else:
            pins = _pins(args, scan)
            if not task and not pins:
                raise ValueError("Supply --task, --task-file, --include, or --requests.")
            candidates = [
                candidate
                for candidate in suggest(scan.files, modules, task, pinned=pins)
                if candidate.score > 0 or candidate.pinned
            ]
            if not candidates:
                raise ValueError(
                    "No files matched the task. Pin files with --include or use overview."
                )
            result = build_bundle(
                scan.files,
                modules,
                candidates,
                task=task,
                budget=args.budget,
                format=format_name,
                extra_context=_evidence(args.context),
                excluded=scan.excluded,
            )
        _check_fresh(scan, args.exclude)
        _write(output, result, scan, force=args.force)
        _summary(result, output, console)
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        Console(stderr=True, markup=False, highlight=False).print(f"Error: {error}")
        return 2
    except (KeyboardInterrupt, EOFError):
        console.print("\nCancelled.")
        return 130
