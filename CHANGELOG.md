# Changelog

All notable changes to Lathe are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-11-23

Initial public release of Lathe — an autonomous terminal AI coding agent powered by dual-model orchestration, local GGUF runtimes, and automated model merging.

### Added

#### Core Orchestration & Reasoning
- **Dual-Model Orchestrator** (`lathe.orchestrator.dual`): Pairs a reasoning Planner model (`DeepSeek-R1`) with an execution Coder model (`Qwen2.5-Coder`). Generates Pydantic-validated structured JSON plans with automated single-retry recovery on malformed output. *(Phase 17)*
- **Interactive Plan Checklist**: Live Rich terminal checklist allowing developers to approve `[y]`, edit in `$EDITOR` `[e]`, or reject `[n]` plans prior to execution. *(Phase 17)*
- **Focused Context Windows**: Each plan step passes only focused instructions, target files, and prior step summaries to the coder. *(Phase 17)*
- **Automated Code Reviewer** (`lathe.orchestrator.review`): `StepReviewer` audits step diffs and test results against a five-point rubric (correctness, step match, no unrelated changes, no secrets, tests pass). Returns structured JSON verdicts (`approve` or `revise`). *(Phase 18)*
- **Intelligent Task Router** (`lathe.orchestrator.router`): Categorizes user prompts into `chat`, `simple`, or `complex` using fast rule heuristics and a lightweight router model. Dispatches requests to read-only tools, single mode, or dual mode. *(Phase 19)*
- **Per-Role Telemetry & Session Stats**: `StatsCollector` records calls, tokens, latency, and tokens/sec per role; renders Rich inspection tables via `/stats` and serializes metrics to `.lathe/sessions/<id>/stats.json`. *(Phase 19)*
- **Autonomous Agent Loop** (`lathe.orchestrator.agent`): Single-agent autonomous execution supporting tool calling, loop detection, thinking events, and optional post-run test `self_check`. *(Phase 13)*

#### Tools & Sandboxing
- **Workspace File Operations** (`lathe.tools.files`): `read_file` with line numbering and size caps; `write_file` with overwrite guards; `list_dir` with ASCII tree rendering; `glob` pattern search. *(Phase 7)*
- **Atomic File Editing** (`lathe.tools.edit`): `edit_file` with exact and whitespace-relaxed matching, ambiguous match detection, unified diff preview, and encoding/newline preservation. *(Phase 10)*
- **Shell Tool** (`lathe.tools.shell`): `run_shell` executes commands within the workspace root, streams live output, and terminates process groups (`SIGKILL`) on timeout. *(Phase 8)*
- **Git Tools** (`lathe.tools.git`): `git_status`, `git_diff`, `git_log`, and `git_commit` with write authorization checks. *(Phase 6)*
- **Test Runner Tool** (`lathe.tools.tests`): `run_tests` auto-detects test runners (`pytest`, `npm test`, `cargo test`, `go test`, `ctest`, `make test`) and extracts failing test blocks for self-correction. *(Phase 18)*
- **Exact & Semantic Search** (`lathe.tools.search`): `grep_search` using ripgrep with Python fallback; `semantic_search` powered by local SQLite vector index. *(Phase 15)*
- **Model Context Protocol (MCP)** (`lathe.memory.mcp`): Stdio MCP client bridging external tools configured under `[mcp]` in `lathe.toml`. *(Phase 9, Phase 22)*

#### Context, Indexing & Memory
- **AST Symbol Indexing** (`lathe.context.repomap`): Tree-sitter parsing for Python, JS/TS, Go, Rust, and C/C++ with Personalized PageRank symbol ranking. *(Phase 11)*
- **Code Chunking & Vector Index** (`lathe.context.index`): Incremental function/class chunking, vector embedding, SQLite storage, and `lathe index` CLI tool. *(Phase 15)*
- **Token Counting & Budgeting** (`lathe.context.budget`): Hugging Face tokenizer loading with disk cache, categorical budget allocation, colored `/tokens` bar chart, and two-stage 75% compaction. *(Phase 16)*
- **Project Memory & Instructions** (`lathe.memory`): `LATHE.md` project rules loading, `/init` repo exploration, `/remember` fact recording, session resumption (`lathe --resume`, `lathe --continue`), and custom slash commands (`.lathe/commands/<name>.md`). *(Phase 22)*

#### Model Merging & Evaluation
- **Interactive Model Merge Wizard** (`lathe.merge`): Combines safetensors models via `mergekit` using SLERP, TIES, DARE-TIES, or Linear averaging. *(Phase 20)*
- **Architecture Compatibility Checks**: Pre-verifies `model_type`, `hidden_size`, `num_hidden_layers`, and tokenizers via `huggingface_hub` before downloading weights. *(Phase 20)*
- **Google Colab Generation**: `lathe merge --colab` produces self-contained GPU notebooks for cloud execution. *(Phase 20)*
- **GGUF Quantization & Ollama Modelfiles**: `lathe merge gguf` converts safetensors with `llama.cpp`, quantizes, generates chat-template Modelfiles, and registers local Ollama models. *(Phase 21)*
- **Lathe Mini-Bench** (`lathe.bench`): 30-task evaluation benchmark measuring pass@1 accuracy, throughput, and tool-call success rates with comparative chart generation (`assets/bench.png`). *(Phase 21)*

#### Safety & Security Hardening
- **Hard Security Blocklist** (`lathe.safety.permissions`): Unconditionally blocks catastrophic commands (`rm -rf /`, `sudo`, piped remote scripts `curl|sh`, `mkfs`, fork bombs). *(Phase 5, Phase 23)*
- **Prompt-Injection Delimiters**: Encloses file contents in `[UNTRUSTED REPOSITORY CONTENT]` structural delimiters to prevent indirect injection attacks. *(Phase 23)*
- **Secret Scrubbing**: `scrub_env` strips API keys and credentials before spawning subprocesses. *(Phase 5, Phase 23)*
- **Workspace Confinement**: `Workspace.resolve_path()` prevents directory traversal and symlink escapes. *(Phase 4)*
- **Non-Destructive Git Checkpoints** (`lathe.safety.checkpoints`): Automatically snapshots working trees before mutations for instant rollback with `lathe undo` or `/undo`. *(Phase 14)*

#### Developer Experience & Distribution
- **Interactive Terminal UI** (`lathe.ui`): `prompt_toolkit` REPL with syntax highlighting, multiline editing (`Alt+Enter`), `@file` autocompletion, status bar, and live streaming markdown. *(Phase 12)*
- **CLI Commands** (`lathe.cli`): `lathe doctor`, `lathe config`, `lathe models`, `lathe merge`, `lathe bench`, `lathe index`, `lathe undo`. *(Phase 1-22)*
- **One-Liner Installers**: Cross-platform `install.sh` (Linux/macOS) and `install.ps1` (Windows). *(Phase 24)*
- **Documentation Site**: Complete MkDocs Material documentation site in `docs/` with automated GitHub Pages deployment workflow. *(Phase 24)*
- **Release Automation**: GitHub Actions workflow for PyPI trusted publishing and automated GitHub Releases. *(Phase 24)*
