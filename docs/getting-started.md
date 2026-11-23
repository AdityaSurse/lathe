# Getting Started

This guide walks you through installing Lathe, verifying your local environment, and launching your first agent coding session.

---

## Installation Options

### Option 1: Astral `uv` Tool (Recommended)

[Astral uv](https://astral.sh/uv) provides isolated, high-speed Python tool execution:

```bash
uv tool install lathe-agent
```

To include model merging with `mergekit`:
```bash
uv tool install "lathe-agent[merge]"
```

### Option 2: pipx

```bash
pipx install lathe-agent
```

### Option 3: Quick Install One-Liners

**Linux / macOS:**
```bash
curl -fsSL https://raw.githubusercontent.com/adityasurse/lathe/main/install.sh | bash
```

**Windows PowerShell:**
```powershell
irm https://raw.githubusercontent.com/adityasurse/lathe/main/install.ps1 | iex
```

---

## Environment Health Check

Before your first session, verify that your local runtime (such as Ollama) and tools are properly detected:

```bash
lathe doctor
```

Output checks:
- Python environment version ($\ge 3.11$)
- Git binary and repository root detection
- Ripgrep (`rg`) availability (falls back to Python search if absent)
- Ollama service reachability and installed models
- Hugging Face token verification (masked for security)

---

## Interactive REPL Mode

Launch the full-featured interactive terminal session in your project root:

```bash
cd /path/to/your/project
lathe
```

### REPL Features:
- **@file autocompletion**: Type `@` followed by filename characters to search repository paths.
- **Multiline Editing**: Press `Alt+Enter` (or `Esc+Enter`) to insert newlines without submitting.
- **Cancel Turn**: Press `Ctrl+C` to cancel a streaming completion or halt a tool.
- **Clean Exit**: Type `/exit` or press `Ctrl+D`.

### Built-in Slash Commands:

| Command | Description |
|---|---|
| `/help` | Display interactive command guide |
| `/mode [single\|dual\|auto]` | Switch agent orchestrator mode |
| `/model [role] [name]` | Switch model assigned to role (`coder`, `planner`, `router`) |
| `/tokens` | Display colored breakdown chart of context budget |
| `/compact` | Force compaction of older conversation turns |
| `/diff` | Display working tree unified diff since session start |
| `/checkpoints` | List checkpoint snapshot history |
| `/undo` | Roll back recent agent edits to previous checkpoint |
| `/clear` | Clear conversation history |
| `/stats` | View telemetry table (tokens/sec, latency, call counts) |

---

## Headless CLI Execution

Execute specific tasks directly from your shell without opening the interactive prompt:

```bash
# Autonomous single-shot execution
lathe "Add input validation to src/auth.py and run pytest"

# Explicit dual-model execution
lathe --dual "Refactor the database connection pool across all services"

# Non-interactive automated execution (bypasses permission prompts)
lathe --auto "Fix typos in README.md"
```
