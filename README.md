# ChatbotHelper

Prepare focused Python project context for browser-based coding chats.

ChatbotHelper reads a local project, helps you select relevant files, and exports a
text or Markdown bundle for manual upload. It runs locally, requires no model API,
and leaves applying code changes to you.

The initial release targets Windows and Python projects. Git is optional at runtime.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then download
or clone this repository. In its folder, run:

```powershell
uv sync --locked
uv run chatbot-helper
```

Python 3.12 or newer is required. uv can provide Python when it is missing.
After dependencies are installed, context preparation needs no network access.

Choose a project folder and one of three options:

1. **Task-based source bundle:** describe the task, review suggested files, and export.
2. **Project overview:** export a compact list of paths, imports, and Python definitions.
3. **Files requested by Copilot:** paste the relative paths requested by your chat,
   review the selection, and export their current source.

Exports are saved under the selected project's `.chatbot-helper` folder by default.
The terminal prints the full destination. Upload the file in your browser chat and
include your task in the message. ChatbotHelper does not upload or send anything.

See the [chat workflow and copy-and-paste prompts](docs/prompts.md) for messages
to send with each export, requesting more files, and reviewing updated source.

## Choosing context

Task suggestions combine filename, symbol, and source-text matches with direct
local imports and related tests. Each suggestion has a reason. You can review
every eligible file, including files that were not suggested.

In the selection screen:

| Input | Action |
| --- | --- |
| `1,3-5` | Replace the selection with those file numbers |
| `add src/example.py` | Add a relative path or glob |
| `remove tests/*` | Remove matching files |
| `show 3` | Preview the first 80 lines of a file |
| `all` / `none` | Select all eligible files / clear the selection |
| `done` | Continue with the current selection |

Reviewed files are included in full. If they exceed the budget, increase the budget
or revise the selection. No source file is silently shortened. Changing project
files during review requires restarting preparation so the export uses current source.

## Overview-first workflow

For an unfamiliar project, generate an overview first. Upload it with your task and
ask the chat to return the relative paths it needs, for example:

```text
shop/billing.py
shop/validation.py
tests/test_billing.py
```

Choose **Files requested by Copilot**, paste that list, and finish with a line
containing `END`. Markdown bullets, backticks, and Windows path separators are
supported. Review the resulting selection and upload the new source bundle.
The overview is navigation material; it does not contain full source implementations.
The [overview-first walkthrough](docs/prompts.md#overview-first-workflow) includes
the prompts for both uploads.

## Commands

The same operations can run without the interactive menu:

```powershell
# Export a project overview.
uv run chatbot-helper overview "C:\Projects\Example"

# Suggest context from a task, and require one particular source file.
uv run chatbot-helper prepare "C:\Projects\Example" --task "Fix invoice rounding" --include "shop/billing.py"

# Build context from paths requested by a chat.
uv run chatbot-helper prepare "C:\Projects\Example" --requests .\requested-files.txt --task-file .\task.txt

# Include an existing traceback, test result, or diff.
uv run chatbot-helper prepare "C:\Projects\Example" --task "Fix invoice rounding" --context .\test-output.txt

# Run the selection menu for a particular project.
uv run chatbot-helper interactive "C:\Projects\Example"
```

Use `--format md` for Markdown instead of the default `.txt`. Both formats use
readable headings and fenced source. `--output` chooses an explicit destination;
its suffix must match the selected format. Existing exports require `--force`.
Existing files inside a project can only be replaced within `.chatbot-helper/`;
choose an external output folder for reusable custom destinations.

Use `--help` on any command for all options. `python -m chatbot_helper` also works
inside the uv environment. To install the command separately from its checkout:

```powershell
uv tool install .
```

## Budgets and omissions

The default export budget is **60,000 characters**, including instructions,
overview material, full sources, and omission reporting. Change it with `--budget`.
The displayed token estimate uses approximately four characters per token; it is
not a measurement of your chat's capacity. Browser upload limits and model context
limits are different, so adjust the budget for the service you use.

In a noninteractive task export, explicitly included/requested files must fit intact;
lower-ranked suggestions may be omitted with a reason. In the interactive menu,
all files you approve must fit. Additional `--context` files must also fit intact.
Large omission reports are compacted to counts when necessary to stay within budget.

## File handling

- Reads Python, common text documentation, and configuration files. Existing logs
  can be supplied with `--context`.
- Honors nested `.gitignore` and `.chatbothelperignore` rules, even without Git.
  Ignore rules also apply to tracked files. An explicit include cannot bypass exclusions.
- Skips environments, caches, generated directories, links, binary files, and files
  larger than 200,000 bytes. Ignored directories are reported once without traversal.
- Excludes credential filenames such as `.env*`, `credentials.*`, and private keys.
  Review exports before uploading; filename rules cannot detect credentials embedded
  in ordinary source files.
- Reads Python encoding declarations and UTF-8 text. Decoded source and line endings
  are retained in UTF-8 exports. Python syntax errors appear in the map, while the
  original file remains available for selection.

Create a `.chatbothelperignore` file in a project for additional Git-style exclusions:

```gitignore
data/
notebooks/
local-settings.json
```

You can also repeat `--exclude PATTERN` on a command. Helper ignore rules cannot
restore a file excluded by Git rules or built-in exclusions. Add `.chatbot-helper/`
to your project's own ignore rules if you want to keep generated exports out of Git.

The Python map uses static analysis. It cannot resolve dynamic imports, and its parser
must support the source syntax. No project modules are imported, no tests or commands
are executed, and no browser automation is used.

## Try the example

```powershell
uv run chatbot-helper interactive .\examples\sample_project
```

Try the task “Reject negative invoice amounts.” Review the billing module, its
validation dependency, and its test before exporting.

## Development

```powershell
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv build
```

CI runs the checks on Windows and Linux with Python 3.12 and 3.14. See
[design notes](docs/design.md) for the selection and export architecture.

MIT licensed.
