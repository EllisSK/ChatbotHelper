# Design

ChatbotHelper prepares context for manual transfer into browser-based coding chats.
The core accepts local files and produces a self-contained export. Terminal input
and file writing stay outside the selection and rendering logic.

## Pipeline

| Module | Responsibility |
| --- | --- |
| `discovery.py` | Discover text and apply file, directory, and ignore rules |
| `python_context.py` | Parse Python signatures/imports and resolve direct local dependencies |
| `selection.py` | Rank task matches, resolve explicit paths, and parse requested-file lists |
| `bundle.py` | Render bounded project maps and complete source bundles |
| `cli.py` | Terminal review, arguments, freshness checks, and UTF-8 file export |

`uv` manages installation and the development environment. The runtime dependencies
are Rich for terminal interaction and PathSpec for Git-style ignore matching.
Python's standard `ast` module supplies the Python index. The tool does not need
an external model, a persistent vector index, Git, or an editor extension.

## Context selection

Explicit relative paths and globs are pinned. Other candidates receive explainable
scores from the task's words, path names, symbol names, source text, local import
relationships, and related tests. Ties use a stable path order. Suggestions remain
editable; ranking does not establish that a file is sufficient or necessary.

Both supported workflows use this inventory:

- **Task first:** suggest source, review the selection, export.
- **Overview first:** export a map, obtain requested paths from the chat, resolve
  them locally, review the selection, export.

The map is structural context, clearly separated from exact source. Imports are
resolved statically, including relative imports and `src` layouts. Dynamic imports
and complete semantic call graphs are outside the initial scope.

## Export contracts

- Files in a source bundle retain their decoded contents and line endings.
- Paths are relative to the selected root. The root's absolute path is not exported.
- The character budget covers the complete export, including its task and metadata.
- Pinned sources and explicitly supplied evidence must fit in full, or export fails.
- Unpinned candidates can be skipped with an omission reason.
- Omission details can compact into counts; complete omitted metadata stays available
  in the core's `BundleResult` object.
- Project changes detected between scanning and writing cancel the export.

By default, outputs live in `.chatbot-helper/`, which discovery excludes. An explicit
destination cannot replace existing project files outside this output directory.
Prepared files are transferred manually; the tool does not submit chat messages or
apply responses.

## References

- [Aider repository maps](https://aider.chat/docs/repomap.html): a compact map can
  complement full source files.
- [Aider's manual handoff](https://aider.chat/docs/usage/copypaste.html): selected
  source, maps, and task instructions can be transferred into a separate chat.
- [Repomix](https://repomix.com/guide/usage): useful prior art for filtering,
  packaging, and reporting context size.
- [Microsoft Copilot uploads](https://support.microsoft.com/en-us/microsoft-365-copilot/file-upload-in-microsoft-copilot):
  text and Markdown are documented upload formats. Upload acceptance does not
  establish how much content a model will use.
- [Python AST](https://docs.python.org/3/library/ast.html): source analysis without
  importing project modules.
- [uv tools](https://docs.astral.sh/uv/guides/tools/): isolated Python tool installation.

## Further development

Potential additions include named selection profiles, explicit symbol excerpts,
transitive dependency controls, and more language adapters. Session histories and
delta-only context require accounting for what a chat still retains, so the initial
release generates complete, independently usable exports.
