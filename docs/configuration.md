# Configuration Reference

Lathe reads configuration from two files:
1. **Global Configuration**: `~/.config/lathe/lathe.toml` (applies across all projects)
2. **Project Configuration**: `./lathe.toml` in your project root (overrides global settings)

To generate a starter configuration file in your project, run:
```bash
lathe config init
```

---

## Full `lathe.toml` Specification

```toml
[project]
# Custom test command override (auto-detected if omitted)
test_command = "pytest"

[settings]
# Operating mode: "auto" (intelligent router), "single" (coder only), or "dual" (planner + coder)
mode = "auto"

# Permission mode: "default" (interactive prompts), "auto", or "yolo"
permission_mode = "default"

# Maximum agent steps before halting execution
max_agent_steps = 25

# Token budget allocated to repository symbol map
repomap_token_budget = 2048

# Enable automated post-run test execution and self-correction in single mode
self_check = true

# ==============================================================================
# Model Roles
# Supported backends: "ollama", "huggingface", "openai-compatible"
# ==============================================================================

[roles.coder]
backend = "ollama"
model = "qwen2.5-coder:7b"
temperature = 0.0
max_tokens = 4096
context_window = 32768
base_url = "http://localhost:11434"

[roles.planner]
backend = "ollama"
model = "deepseek-r1:8b"
temperature = 0.0
max_tokens = 4096
context_window = 16384
base_url = "http://localhost:11434"

[roles.reviewer]
backend = "ollama"
model = "deepseek-r1:8b"
temperature = 0.0
max_tokens = 2048
context_window = 16384
base_url = "http://localhost:11434"

[roles.router]
backend = "ollama"
model = "qwen2.5-coder:1.5b"
temperature = 0.0
max_tokens = 1024
context_window = 8192
base_url = "http://localhost:11434"

# ==============================================================================
# Semantic Code Search & Embeddings
# ==============================================================================

[embeddings]
# Provider: "ollama", "sentence-transformers", or "huggingface"
provider = "ollama"
model = "nomic-embed-text"
base_url = "http://localhost:11434"

# ==============================================================================
# Model Context Protocol (MCP) Client Integrations
# ==============================================================================

[mcp.servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
env = { GITHUB_PERSONAL_ACCESS_TOKEN = "env:GITHUB_TOKEN" }

[mcp.servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "./docs"]
```

---

## Instructions & Custom Commands

### Project Instructions (`LATHE.md`)
Create a `LATHE.md` file in your repository root (or globally at `~/.config/lathe/LATHE.md`) to define stack conventions, testing guidelines, and architectural rules. Lathe automatically loads `LATHE.md` into the agent's system prompt and planning context.

Run `/init` inside Lathe to have the agent explore the repository and draft a baseline `LATHE.md`.

### Custom Slash Commands (`.lathe/commands/<name>.md`)
Create markdown templates in `.lathe/commands/<name>.md` to define project-specific workflows accessible via `/<name>`.

Example `.lathe/commands/fix-issue.md`:
```markdown
Read issue description: $ARGS
Inspect the relevant source files and tests, write a reproduction test, implement the fix, and verify tests pass.
```
Invoked in the terminal via `/fix-issue 42`.
