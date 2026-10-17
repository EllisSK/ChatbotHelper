# Chat workflow and prompts

ChatbotHelper prepares local project context for manual upload to a browser chat.
You run the tool; the chat reads the generated files and recommends edits.
You apply those edits and run any suggested checks locally.

Copy the prompts below into your chat after uploading the corresponding export.
Replace square-bracket placeholders with your task and constraints. The attachment
is the generated `.txt` or `.md` file; the terminal prints its location.

## Start ChatbotHelper

From the ChatbotHelper checkout, run:

```powershell
uv sync --locked
uv run chatbot-helper
```

Select your project's folder when prompted. Exports are saved under that project's
`.chatbot-helper` folder by default. Every export is a snapshot of the source at
the time it was prepared.

Choose the workflow that suits the task:

| Workflow | Start with | Next step |
| --- | --- | --- |
| Task first | Option 1: Task-based source bundle | Review suggested files and upload their source |
| Overview first | Option 2: Project overview | Ask the chat for paths, then use option 3 to export their source |

The tool uses local text matches, imports, and related tests to suggest context.
Review its selection; the suggestions may need adjustment. An overview contains
paths, imports, and definition summaries. A source bundle includes complete selected
files, the task, navigation summaries, and an omission report.

## Task-first workflow

1. Choose **1: Task-based source bundle**.
2. Describe the change and its expected behaviour.
3. Review the suggested files. Enter `done` to continue, or adjust the selection
   with file numbers, `add PATH_OR_GLOB`, or `remove PATH_OR_GLOB`.
4. Export and upload the generated file to your chat.
5. Send this prompt:

```text
Use the attached ChatbotHelper source bundle for this task:
[Describe the change, current behaviour, and expected behaviour.]

Constraints:
[List requirements, compatibility needs, or areas to leave unchanged.]

Read the task, project map, included source, and omission report. Base
your recommendations on the supplied source. If essential context is
missing, request the exact project-relative file paths, one per line
in a fenced text block, and wait for me to upload them. Put any
explanation outside that block.

When you have enough context:
- Explain the proposed change briefly.
- Identify each file to change using its relative path.
- Provide clearly identified replacement functions or code blocks,
  including any changed imports. Include full contents for new files.
- Include relevant test changes and commands I should run to verify them.
- Distinguish suggested checks from checks actually performed.
```

If the chat requests more files, follow the requested-files step below.

## Overview-first workflow

### 1. Upload an overview

Choose **2: Project overview**, enter your task, and export. Upload the generated
file and send:

```text
The attached file is a ChatbotHelper project overview. It contains
paths, imports, and definition summaries rather than full implementations.

My task is:
[Describe the change, current behaviour, and expected behaviour.]

Constraints:
[List requirements or compatibility needs.]

Identify the source files, tests, and configuration you need before
recommending changes. Start with the smallest useful set.

Return their exact project-relative paths from the overview, one per
line in a fenced text block. Put any explanation outside that block.

Wait for me to upload the source bundle before proposing edits.
```

### 2. Export the requested files

The chat might return a list like this:

```text
shop/billing.py
shop/validation.py
tests/test_billing.py
```

Run ChatbotHelper again, select the same project folder, and choose
**3: Files requested by Copilot**. Enter the task and paste the path list when
prompted. Finish with a separate line containing:

```text
END
```

Markdown bullets, backticks, and Windows path separators are supported.
Paths must refer to available files inside the selected project. Review the
selection, export, and upload the source bundle in the same conversation.

### 3. Ask for edits

Send this prompt with the new source bundle:

```text
The new attachment contains the requested source. Treat it as the
current snapshot for those files, superseding earlier versions.

Continue with this task:
[Restate the change and any constraints.]

If essential context is still missing, request more project-relative
paths, one per line in a fenced text block, and wait for me to provide
them. Put any explanation outside that block.

When you have enough context:
- Explain the proposed change briefly.
- Identify each file to change using its relative path.
- Provide clearly identified replacement functions or code blocks,
  including any changed imports. Include full contents for new files.
- Include relevant test changes and commands I should run to verify them.
- Distinguish suggested checks from checks actually performed.
```

Repeat the requested-files step whenever the chat needs more source. The same step
also works for additional file requests during the task-first workflow.

## After applying changes

Apply the recommended edits locally and run the suggested checks. Regenerate
context from the updated source, upload the new bundle, and send:

```text
I have applied changes for this task:
[Restate the task and any constraints.]

The new attachment is the current snapshot for its included files.
Use it in place of earlier versions of those files.

Checks I ran and their results:
[Paste the commands and actual results, or say that checks have not run.]

Review the updated source for correctness and regressions. If more
context is needed, request project-relative paths in a fenced text
block and wait for the source. Recommend any further edits and checks.
```

Existing traceback, test-output, or diff files can also be included with
`--context` when starting a command:

```powershell
uv run chatbot-helper interactive "C:\Projects\Example" --context .\test-output.txt
```

The context-file path is relative to the terminal's current folder unless you
supply an absolute path. The tool reads existing output; it does not run the
commands that produced it. Use option 1 or 3 to include this evidence in a source
bundle.

## Starting a new conversation

Upload a freshly generated source bundle and use the task-first prompt. Include
any decisions or constraints that still matter. File requests and earlier decisions
are transferred manually; ChatbotHelper does not track the chat's retained context.

## Try the example

```powershell
uv run chatbot-helper interactive .\examples\sample_project
```

Use the task: "Reject negative invoice amounts while preserving existing behaviour
for zero and positive amounts." Try both workflows and review the selected source
before uploading it.
