# 1.0.13 — 2026-08-28

## Features

- **Length-truncated responses** now continue automatically instead of failing the turn.
- **Hooks** can now ask the user to confirm a tool call instead of always allowing or denying.
- **Hooks** can now request deferral or add context shown to the model after a tool runs.
- **Session close** now records detailed timing data for performance analysis.
- **Credit limit upsell** now offers a Try Again button to retry the last prompt.
- **Pasted images** now show a live pixel preview in the prompt box on iTerm2.

## Bug Fixes

- **Transient inference failures** (stalls, drops, 5xx) now retry automatically instead of ending the turn.
- **Windows users** can now correctly open ~/.grok and worktree sessions.
- **Session data** is now more reliably saved after prompts and on power loss.
- **Compaction failures** now show the actual error instead of a generic message.
- **Truncation error messages** now show the right guidance instead of suggesting an unhelpful retry.
- **Truncated tool calls** are now executed instead of failing the turn when arguments are complete.
- **Images larger than 2000px** no longer brick sessions on many-image requests.
- **Wrapped hyperlinks** in the pager now remain fully clickable on Windows Terminal instead of only the first line.
- **Recurring scheduled tasks** now include a reminder to stop the monitor when work finishes.
- **Scheduled task IDs** are now full UUID strings, preventing collisions when tasks are created in the same millisecond.

## Performance

- **Subagent spawning** is faster when connections drop during bursts.
- **Session startup** with MCP servers is now much faster when auth is already configured.
- **MCP server startup** no longer stalls behind a fixed batch size.
- **CLI downloads** are now compressed, making fresh installs and updates substantially faster.


# 1.0.12 — 2026-08-27

## Features

- **Credit-limit upsell** now includes a Try Again option. Max-tier users see the same question modal without Upgrade tier.

## Bug Fixes

- **Copying wrapped table cells** no longer inserts unwanted spaces at line breaks.
- **MCP server connections** that fail transiently now retry instead of staying unavailable.
- **Waiting on subagents** after an interjection no longer blocks on unrelated background work.
- **Prompt blocks** now show friendly hook descriptions instead of internal IDs.
- **Truncation error message** no longer suggests asking for a shorter answer.
- **Context estimates** for conversations with reasoning are now more accurate.
- **Token usage** after rewinding or switching modes now matches the actual server-reported count instead of overestimating.
- **Context bar** now updates immediately when auto-compaction begins instead of waiting until it finishes.
- **File system monitoring** for .NET projects no longer creates excessive watchers on Linux.
- **Auto recap** no longer appears while a background task or monitor wake turn is streaming.

## Performance

- **Worktree creation** is faster by skipping stale reflog copies.


# 1.0.11 — 2026-08-26

## Features

- **Headless sessions** are now browsable in the resume picker without mixing into default history.
- **Default permission mode** for new interactive sessions is now configurable.
- **Turn duration** now appears in session history after resume.
- **Turn footers** (Worked for, cancelled, failed) now appear after /resume.
- **mkdir and touch** no longer prompt in auto mode or safe-command lists.
- **Subagent messages** are now allowed automatically in permission Auto mode.
- **Headless sessions** can now auto-allow permission prompts via a startup hint.

## Bug Fixes

- **Permission prompts** for common command chains and subcommands are now more reliable.
- **Blocked prompts** no longer appear in conversation history or scrollback after restart.
- **Background monitors** no longer have a 10-hour default timeout.
- **Mouse input** at the right margin no longer types characters into the prompt on certain terminals.
- **Pasting text ending in a newline** no longer accidentally submits the prompt on some terminals.
- **Auto mode** now shows a permission card when the classifier blocks an action on interactive sessions.
- **Image previews** no longer leave ghost artifacts when using the Kitty protocol on Warp.
- **Expanded Execute tool output** no longer snaps closed during live progress.
- **/voice** now falls back to parec/arecord on older PipeWire installs.

## Performance

- **Background command waits** now finish as soon as the process exits.


# 1.0.10 — 2026-08-24

## Performance

- **grok clone** now reuses matching local checkouts as linked worktrees for faster session creation.


# 1.0.9 — 2026-08-24

## Features

- **New sessions in the interactive TUI** now start in auto mode by default for fewer approval prompts.
- **/feedback now supports attaching images** (screenshots etc.).
- **The / slash menu** is now ordered by recency and groups skills below commands for easier navigation.
- **/workflow** now accepts --agent-budget N or an agent_budget JSON field to set child-agent limits.
- **/workflow** now accepts --effort LEVEL or an effort JSON field to set child reasoning effort.
- **MCP servers** now receive a grok-cli User-Agent header so providers can attribute traffic.
- **Dashboard** now lets you start new agents in Auto mode via Shift+Tab.
- **Workflows** now appear alongside skills in the model prompt so the agent can launch them by name.
- **`/edit-prompt`** now opens an external editor from the full TUI, not only minimal mode.
- **Up arrow** on an empty prompt now selects queued follow-ups first instead of opening history.
- **/plugin** now works as an alias for **/plugins** in the TUI.
- **Plugin-provided agents** now appear in the **/agents** modal and can be toggled.
- **/minimal** and **/fullscreen** now switch instantly inside the running session without restarting or losing the current turn.
- The configurable status line row now appears at the bottom of minimal mode as well as fullscreen.
- **grok clone** now fetches only the selected branch tip by default, with --full-history for legacy full clones.
- **grok clone** can now reuse a matching local checkout as a linked worktree instead of always fetching from the network.

## Bug Fixes

- **Subagent tasks** are more resilient to temporary rate limits and will retry instead of failing immediately.
- **Narrow allow rules for Bash commands** now correctly permit file writes without extra prompts.
- **Rules** containing markdown headings now render correctly in the prompt.
- **/new** and **/clear** now preserve the last-chosen reasoning effort instead of resetting to the model default.
- **Prompt dropdowns** (slash, history, file search) now have consistent left alignment with the composer.
- **History** now shows every command, slash command, and memory note in the order you typed them.
- **Collapsed tool-call rows** no longer show a vertical accent line beside the status diamond.
- **Hint text** above the prompt now lines up with the text you type.
- **Pressing Esc** while peeking at a conversation from the dashboard now closes open modals instead of leaving the view.
- **`/copy`** now preserves markdown formatting such as headings and code fences.
- **Sending a new message** while a shell command is running now moves the command to the background instead of cancelling it.
- **grok mcp add** now correctly treats bare http(s):// URLs as HTTP servers instead of stdio commands.
- Plan mode no longer incorrectly blocks subagent spawns as file edits outside plan.md.
- MCP servers that share a URL but have different names are now kept as separate entries instead of being collapsed.
- Subagents and workflow-spawned agents no longer receive the workflow tool that only top-level sessions can use.
- Memory results are now presented as historical context that should be verified against live sources before use.
- **Interactive grok sessions** now start in ask mode by default again instead of auto.
- **Minimal mode** no longer truncates subagent wake-turn replies after the first token.

## Performance

- **Concurrent subagents** no longer trigger rate-limit errors during bursts.
- **MCP server connections** no longer delay session startup when many servers are configured.


# 1.0.8 — 2026-08-20

## Features

- MCP servers can now ask for form input or URL consent through the same popup used for questions.
- Ctrl+S now stashes the current prompt draft so you can send something else and restore it later.
- ** /workflow** now autocompletes saved workflow names and shows only valid runs for pause/resume/stop/save.

## Bug Fixes

- Downloading a folder that contains only one file now produces a zip that still extracts as a folder.
- Failed tool calls for tools the model invented now clearly state the tool does not exist.
- **Status line** refresh timer now uses consistent naming and no longer shows errors on deliberately hidden rows.
- **Workflow agent rows** now display current context usage instead of cumulative token counts.
- **Follow-up messages** now send immediately while waiting on a subagent or task, including after using /btw.
- Subagents and workflow-spawned agents no longer see the workflow tool, which can only be launched from a top-level session.

## Performance

- Opening many subagents at once no longer freezes the interface while loading their history.
- **Concurrent subagents** now start much faster and no longer freeze the parent session.


# 1.0.7 — 2026-08-19

## Features

- Users hitting startup timeouts can now raise the connect budget with the `GROK_CONNECT_UI_TIMEOUT_SECS` environment variable.
- Permission prompts now show "Always allow" and "Never allow" options by default.
- Users can now delete scheduled background loops directly from the tray.
- **Status line command** scripts can now run on a timer via refresh_interval in config.toml.
- **Permission prompts** now offer a 'Never allow' choice for MCP tools and web-fetch domains that persists per project.
- **Workflows tab** added to the extensions modal (Ctrl+L or /plugins) listing installed workflows with name, source, and description.
- **New /workflows** command opens the Workflows catalog tab; use **/workflow runs** to view live workflow runs.
- **Bare /workflow** (or /workflow runs) now lists active and recent workflow runs with status and progress instead of usage help.
- **Workflows** row added to the Ctrl+P command palette, opening the Workflows catalog tab.

## Bug Fixes

- **MCP server connections** in non-interactive sessions no longer incorrectly require authentication for tokenless servers.
- Fixed startup timeouts caused by concurrent auth refreshes across multiple sessions.
- **Tool call loops** are interrupted earlier to avoid wasting time on repeated identical actions.
- **Subagents** no longer receive the ask-user-question tool.
- Bare email addresses are now turned into clickable mailto links in the pager.


# 1.0.6 — 2026-08-18

## Breaking Changes

- **Subagent spawning** no longer accepts capability_mode; tool access is now controlled only by agent type.

## Features

- **Shift+arrow keys** now extend text selections in the prompt like a standard text field.
- **Optional status line** can now display live session info or script output at the bottom of the pager.
- **grok clone** can now fetch a repo into a content store and mount a projected working tree.

## Bug Fixes

- **Fixed session startup hangs** on large or unhealthy git repositories.
- **Queued messages** during goals no longer starve, and editing queued prompts works reliably.
- **Consent notice** on first launch now shows clickable links and handles keyboard/mouse correctly.
- **Ctrl+C then edit** a prompt now correctly removes the original text from the conversation.
- **Double-clicking** a terminal command result now shows the complete output instead of a preview.
- **Consent notice links** are now stricter and more reliable on all terminals.
- **Video generation** now surfaces a clear ZDR error instead of raw API responses when output storage is required.
- **Project hooks** on Windows now correctly expand $CLAUDE_PROJECT_DIR when invoking PowerShell scripts.


