<div align="center">

<img src="assets/banner.svg" alt="Lathe — Turn prompts into code. Locally." width="100%" />

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue?style=for-the-badge&logo=apache&logoColor=white)](LICENSE)
[![Ollama](https://img.shields.io/badge/local_runtime-Ollama-black?style=for-the-badge&logo=ollama&logoColor=white)](https://ollama.ai)
[![Hugging Face](https://img.shields.io/badge/providers-Hugging%20Face-FFD21E?style=for-the-badge&logo=huggingface&logoColor=black)](https://huggingface.co)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=for-the-badge&logo=github)](CONTRIBUTING.md)
[![Status](https://img.shields.io/badge/status-building%20in%20public-orange?style=for-the-badge)](https://github.com)

</div>

Autonomous terminal coding agent combining open-source local LLMs, dual-model orchestration, and automated model merging.

---

## 🖥️ Terminal Experience

<div align="center">
  <img src="assets/demo.svg" alt="Lathe Terminal Demo" width="100%" />
</div>

Interactive terminal interface with automated planning, structured diff generation, AST review, and permission prompts.

---

## 🗺️ Feature Architecture Map

```mermaid
mindmap
  root((Lathe Agent))
    Agent Loop
      Autonomous execution
      Diff review step
      Auto retry on test fail
    Dual LLM
      Planner DeepSeek-R1
      Coder Qwen2.5-Coder
    Router
      Complexity scoring
      Fast path dispatch
    Tool Registry
      File operations
      Precise search
      Shell execution
      Git integration
    Lathe Merge
      Mergekit SLERP & TIES
      llama.cpp quantize
      Ollama Modelfile
    Safety System
      Permission gates
      Blocked command list
      Session always-allow
    Memory Engine
      Project AST index
      Session compaction
    Terminal UI
      Streaming tokens
      Rich diffs
      Interactive prompts
```
Complete feature landscape spanning autonomous orchestration, dual-model inference, and local tool execution.

---

## 🏗️ High-Level System Architecture

```mermaid
flowchart LR
    classDef cliStyle fill:#1e293b,stroke:#38bdf8,stroke-width:2px,color:#f8fafc;
    classDef coreStyle fill:#1e1b4b,stroke:#818cf8,stroke-width:2px,color:#f8fafc;
    classDef backendStyle fill:#701a75,stroke:#f472b6,stroke-width:2px,color:#f8fafc;
    classDef toolStyle fill:#78350f,stroke:#fbbf24,stroke-width:2px,color:#f8fafc;
    classDef envStyle fill:#064e3b,stroke:#34d399,stroke-width:2px,color:#f8fafc;

    subgraph Entry ["🖥️ Client Entry"]
        CLI["lathe CLI"]:::cliStyle
        Session["Session Manager"]:::cliStyle
    end

    subgraph Engine ["🧠 Orchestration Engine"]
        Router{"Task Router"}:::coreStyle
        Planner["Planner / Reviewer"]:::coreStyle
        Coder["Coder Model"]:::coreStyle
    end

    subgraph Backends ["🔌 LLM Providers"]
        Ollama["Ollama (Local GGUF)"]:::backendStyle
        HF["Hugging Face API"]:::backendStyle
        OpenAIComp["OpenAI-Compatible"]:::backendStyle
    end

    subgraph Tools ["🧰 Tool Registry"]
        Files["File System"]:::toolStyle
        Edit["Diff & Patch"]:::toolStyle
        Shell["Terminal Shell"]:::toolStyle
        Git["Git Actions"]:::toolStyle
        Search["AST & Grep"]:::toolStyle
        Tests["Test Runner"]:::toolStyle
    end

    Workspace[("📂 Project Workspace")]:::envStyle

    CLI --> Session
    Session --> Router
    Router --> Planner
    Router --> Coder
    Planner <--> Coder
    Planner --> Backends
    Coder --> Backends
    Planner --> Tools
    Coder --> Tools
    Tools --> Workspace
```
Modular decoupling of user sessions, multi-model orchestration, provider backends, and sandboxed workspace tools.

---

## 🔄 Autonomous Agent Loop

```mermaid
flowchart TD
    classDef startStyle fill:#1e293b,stroke:#38bdf8,stroke-width:2px,color:#f8fafc;
    classDef stepStyle fill:#1e1b4b,stroke:#818cf8,stroke-width:2px,color:#f8fafc;
    classDef condStyle fill:#78350f,stroke:#fbbf24,stroke-width:2px,color:#f8fafc;
    classDef passStyle fill:#064e3b,stroke:#34d399,stroke-width:2px,color:#f8fafc;
    classDef failStyle fill:#7f1d1d,stroke:#f87171,stroke-width:2px,color:#f8fafc;

    Task(["Task Prompt"]):::startStyle --> Gather["Gather Context & Index Repo"]:::stepStyle
    Gather --> Plan["Planner: Formulate Step-by-Step Plan"]:::stepStyle
    Plan --> StepStart["Begin Next Plan Step"]:::stepStyle

    StepStart --> CoderDiff["Coder: Generate Unified Patch / Diff"]:::stepStyle
    CoderDiff --> RevApprove{"Reviewer Approves Diff?"}:::condStyle

    RevApprove -- "No: Needs revision" --> CoderDiff
    RevApprove -- "Yes: Verified" --> Apply["Apply Patch to Workspace"]:::stepStyle

    Apply --> RunTests["Execute Verification / Tests"]:::stepStyle
    RunTests --> TestPass{"Tests Pass?"}:::condStyle

    TestPass -- "Yes" --> NextStep{"More Steps Left?"}:::condStyle
    NextStep -- "Yes" --> StepStart
    NextStep -- "No" --> Summary(["Task Completed & Summary"]):::passStyle

    TestPass -- "No" --> RetryCheck{"Retry Count < 2?"}:::condStyle
    RetryCheck -- "Yes" --> FixStep["Coder: Ingest Test Failure & Repair"]:::failStyle
    FixStep --> Apply
    RetryCheck -- "No: Exceeded" --> Halt(["Halt & Solicit User Guidance"]):::failStyle
```
Closed-loop verification cycle enforcing dual-model review and automated test validation before each commit.

---

## 🤝 Task Handoff Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Router as 🧭 Router
    participant Planner as 📋 Planner
    participant Coder as 💻 Coder
    participant Reviewer as 🛡️ Reviewer
    participant Tools as 🧰 Tools & Shell

    User->>Router: lathe "Add JWT bearer auth"
    Router->>Planner: Route complex refactor
    Planner->>Tools: Read workspace AST & auth/middleware.py
    Tools-->>Planner: File contents & dependencies
    Planner->>Coder: Plan step 1: Generate bearer token patch
    Coder-->>Reviewer: Proposed diff for auth/middleware.py
    Reviewer->>Reviewer: Verify syntax, security & diff scope
    Reviewer-->>User: Request permission to write file
    User-->>Reviewer: Permission granted [y]
    Reviewer->>Tools: Apply unified diff patch
    Tools-->>Reviewer: File written successfully
    Reviewer->>Tools: Run pytest tests/test_auth.py
    Tools-->>Planner: Test output (All passed)
    Planner-->>User: Step summary & final changes report
```
Step-by-step collaboration between user authorization, specialized LLM roles, and local filesystem tools.

---

## 🛡️ Permission & Safety State Machine

```mermaid
stateDiagram-v2
    [*] --> RequestAction: Agent invokes tool

    state RequestAction {
        [*] --> CheckType
        CheckType --> ReadOperation: read_file / search / ast
        CheckType --> MutatingOperation: write_file / shell / git_push
        CheckType --> DangerousOperation: rm -rf / git reset --hard
    }

    ReadOperation --> AutoAllow: Safe read-only
    AutoAllow --> Execute: Immediate execution

    MutatingOperation --> CheckAlwaysAllow: Check session whitelist
    CheckAlwaysAllow --> Execute: Already in session whitelist
    CheckAlwaysAllow --> PromptUser: First time this session

    state PromptUser {
        [*] --> AwaitingResponse
        AwaitingResponse --> Denied: [n] Reject
        AwaitingResponse --> ApprovedOnce: [y] Single approval
        AwaitingResponse --> RememberAllowed: [a] Always allow for session
    }

    RememberAllowed --> UpdateWhitelist: Store in session state
    UpdateWhitelist --> Execute

    ApprovedOnce --> Execute

    DangerousOperation --> DenyBlocked: Match blocked command rule
    DenyBlocked --> AbortAction: Hard security block

    Denied --> AbortAction
    Execute --> [*]: Return result to LLM
    AbortAction --> [*]: Return permission error to LLM
```
Multi-tiered authorization pipeline preventing destructive shell commands while streamlining trusted developer workflows.

---

## 🧬 `lathe merge` Model Pipeline

```mermaid
flowchart LR
    classDef hfStyle fill:#701a75,stroke:#f472b6,stroke-width:2px,color:#f8fafc;
    classDef mergeStyle fill:#064e3b,stroke:#34d399,stroke-width:2px,color:#f8fafc;
    classDef quantStyle fill:#1e1b4b,stroke:#818cf8,stroke-width:2px,color:#f8fafc;
    classDef deployStyle fill:#78350f,stroke:#fbbf24,stroke-width:2px,color:#f8fafc;

    subgraph HFModels ["🤗 Hugging Face Sources"]
        ModelA["Model A (HF Safetensors)"]:::hfStyle
        ModelB["Model B (HF Safetensors)"]:::hfStyle
    end

    subgraph MergekitEngine ["⚙️ mergekit Engine"]
        Config["mergekit YAML Config (SLERP / TIES)"]:::mergeStyle
        MergedFP16["Merged Model (16-bit Safetensors)"]:::mergeStyle
    end

    subgraph LlamaCpp ["📦 Conversion & Quantization"]
        Convert["llama.cpp convert-hf-to-gguf"]:::quantStyle
        Quantize["Quantize: Q4_K_M GGUF"]:::quantStyle
    end

    subgraph LocalServe ["🚀 Ollama Runtime"]
        Modelfile["Ollama Modelfile Generation"]:::deployStyle
        OllamaLoad["ollama create & serve"]:::deployStyle
        LatheBench["lathe bench evaluation"]:::deployStyle
    end

    ModelA --> Config
    ModelB --> Config
    Config --> MergedFP16
    MergedFP16 --> Convert
    Convert --> Quantize
    Quantize --> Modelfile
    Modelfile --> OllamaLoad
    OllamaLoad --> LatheBench
```
Automated pipeline merging weights from dual model checkpoints, converting to GGUF, and deploying to Ollama.

---

## ⚡ Decoder-Only Transformer Architecture

<div align="center">
  <img src="assets/transformer.svg" alt="Decoder-Only Transformer Block" width="100%" />
</div>

Internal neural layer structure of autoregressive foundation models executing reasoning and code generation in Lathe.

---

## 📐 Weight Interpolation & Manifold Merging

<div align="center">
  <img src="assets/merge.svg" alt="Lathe Merge SLERP Interpolation" width="100%" />
</div>

Spherical linear interpolation (SLERP) computing geodesic weight trajectories between reasoning and coding models.

---

## 📊 Model Selection Trade-Offs

```mermaid
quadrantChart
    title Model Selection Trade-offs (Illustrative)
    x-axis Low Speed --> High Speed
    y-axis Basic Code Quality --> Frontier Code Quality
    quadrant-1 High Speed & Top Quality
    quadrant-2 High Latency & Top Quality
    quadrant-3 Low Speed & Basic Quality
    quadrant-4 Fast & Lightweight
    "1.5B local": [0.85, 0.35]
    "7B local": [0.55, 0.65]
    "32B API": [0.25, 0.90]
    "merged 7B": [0.55, 0.78]
```
Qualitative balance between token throughput and code quality across local and cloud configurations.

---

## 🍰 Context Window Target Budget

```mermaid
pie title Target Context Window Budget
    "System Prompt & Guidelines" : 10
    "Repository AST Map" : 15
    "Open & Referenced Files" : 35
    "Active Conversation & Steps" : 20
    "Tool Results & Test Logs" : 20
```
Recommended allocation preventing context starvation across file references, conversation history, and tool feedback.

---

## 📅 24-Phase Implementation Roadmap

```mermaid
gantt
    title Lathe 24-Phase Implementation Roadmap
    dateFormat X
    axisFormat Phase %s

    section Stage 1: Foundations
    Phase 1: Project Blueprint & Visual Specs :done, p1, 0, 1
    Phase 2: Configuration & CLI Shell :active, p2, 1, 2
    Phase 3: Ollama Local Runtime Client :p3, 2, 3
    Phase 4: HF Inference Providers Client :p4, 3, 4
    Phase 5: Tokenizer & Context Manager :p5, 4, 5

    section Stage 2: Tool Registry
    Phase 6: File System Tools :p6, 5, 6
    Phase 7: AST Symbol Graph & Repo Map :p7, 6, 7
    Phase 8: Unified Diff & Patch Engine :p8, 7, 8
    Phase 9: Sandboxed Shell Execution :p9, 8, 9
    Phase 10: Git Status & Branch Automation :p10, 9, 10
    Phase 11: Pytest Test Harness & Runner :p11, 10, 11

    section Stage 3: Agent Brain
    Phase 12: Prompt Templates & Personas :p12, 11, 12
    Phase 13: Core Orchestrator Loop :p13, 12, 13
    Phase 14: Step Planner & Decomposer :p14, 13, 14
    Phase 15: Automated Diff Reviewer :p15, 14, 15
    Phase 16: Failure Repair Loop & Retries :p16, 15, 16

    section Stage 4: Dual-LLM & Merge
    Phase 17: Complexity Task Router :p17, 16, 17
    Phase 18: Dual-Model Handshake Protocol :p18, 17, 18
    Phase 19: lathe mergekit Integrator :p19, 18, 19
    Phase 20: GGUF Quantization Pipeline :p20, 19, 20
    Phase 21: Model Evaluation & Benchmarks :p21, 20, 21

    section Stage 5: Ship It
    Phase 22: Session Memory & History Compaction :p22, 21, 22
    Phase 23: Rich Terminal UI & Streaming :p23, 22, 23
    Phase 24: End-to-End Hardening & Packaging :p24, 23, 24
```
Structured five-stage release plan advancing from core primitives to advanced multi-model merging and production distribution.

---

## 🌿 Phase Git Branching Strategy

```mermaid
gitGraph
    commit id: "init-repo"
    commit id: "docs-spec"
    branch phase-1-readme
    checkout phase-1-readme
    commit id: "add-svgs"
    commit id: "add-mermaid-spec"
    checkout main
    merge phase-1-readme id: "merge-p1"
    branch phase-2-cli
    checkout phase-2-cli
    commit id: "cli-parser"
    commit id: "config-loader"
    checkout main
    merge phase-2-cli id: "merge-p2"
    branch phase-3-ollama
    checkout phase-3-ollama
    commit id: "ollama-client"
    checkout main
    merge phase-3-ollama id: "merge-p3"
    branch phase-4-hf-api
    checkout phase-4-hf-api
    commit id: "hf-provider-client"
    checkout main
    merge phase-4-hf-api id: "merge-p4"
    branch phase-5-context
    checkout phase-5-context
    commit id: "token-counter"
    commit id: "context-budgeter"
    checkout main
    merge phase-5-context id: "merge-p5"
```
Isolated phase branches merging sequentially into main with end-to-end integration verification.

---

## 🎛️ Reference Tables & Structure

### 💻 CLI Commands

| ⚡ Command | 📝 Purpose | 🔧 Key Options |
|:---|:---|:---|
| `lathe` | Start interactive agent terminal session | `--model`, `--planner`, `--router` |
| `lathe "<prompt>"` | Run single prompt autonomously to completion | `--auto-approve`, `--max-steps 10` |
| `lathe --plan-only` | Analyze repository and print execution plan | `--output-plan plan.json` |
| `lathe merge` | Merge two Hugging Face models using mergekit | `--method slerp`, `--quant q4_k_m` |
| `lathe bench` | Evaluate model pair on local coding challenges | `--suite syntax,refactor,tests` |
| `lathe models` | List available local Ollama and Hugging Face models | `--download`, `--provider hf` |
| `lathe doctor` | Validate Ollama, llama.cpp, git, and HF tokens | `--fix` |

CLI interface for interactive coding, non-interactive CI automation, model merging, and diagnostics.

### ⌨️ In-Session Slash Commands

| 🪄 Command | 🎯 Action | 💡 Example |
|:---|:---|:---|
| `/help` | Display interactive command and tool reference | `/help tools` |
| `/plan` | Show current multi-step execution checklist | `/plan` |
| `/diff` | Inspect active pending diff before file write | `/diff auth/middleware.py` |
| `/run` | Execute shell or test command manually | `/run pytest -v` |
| `/compact` | Compact conversation history preserving AST context | `/compact` |
| `/model` | Switch active Planner, Coder, or Router model | `/model coder qwen2.5-coder:7b` |
| `/clear` | Clear terminal screen and temporary scratchpad | `/clear` |
| `/exit` | Gracefully terminate session and save progress | `/exit` |

Interactive commands available during agent execution sessions.

### ⚙️ Recommended Model Pairs by Hardware

| 🖥️ Hardware Tier | 🧭 Router Model | 📋 Planner / Reviewer | 💻 Coder Model | 🚀 Backend Mode |
|:---|:---|:---|:---|:---|
| **CPU Only (16GB RAM)** | `Qwen2.5-Coder-1.5B (Q4)` | `Qwen2.5-Coder-7B (Q4)` | `Qwen2.5-Coder-7B (Q4)` | Ollama Local |
| **6–8GB GPU (RTX 3060/4060)** | `Qwen2.5-Coder-1.5B (Q4)` | `DeepSeek-R1-Distill-7B (Q4)` | `Qwen2.5-Coder-7B (Q4)` | Ollama Local |
| **16GB+ GPU / Apple Silicon** | `Qwen2.5-Coder-7B (Q4)` | `DeepSeek-R1-Distill-14B (Q4)` | `Qwen2.5-Coder-14B (Q4)` | Ollama Local |
| **API Only / Hybrid** | Fast Local 1.5B or API | `DeepSeek-R1 (API)` | `Qwen2.5-Coder-32B-Instruct` | HF Inference Providers |
| **Lathe Merged** | Fast Local 1.5B | `lathe-hybrid-7b (SLERP)` | `lathe-hybrid-7b (SLERP)` | Ollama Local (Merged) |

Hardware-adapted configurations optimizing memory footprint, latency, and code accuracy.

### 📁 Project Folder Layout

```text
lathe/
├── assets/                  # High-resolution architectural and terminal SVGs
│   ├── banner.svg           # Project hero banner
│   ├── demo.svg             # Terminal workflow preview
│   ├── merge.svg            # SLERP weight interpolation schematic
│   └── transformer.svg      # Decoder-only transformer block diagram
├── lathe/                   # Core Python application package
│   ├── __init__.py          # Package entrypoint
│   ├── cli.py               # CLI parser and argument handler
│   ├── config.py            # Environment and config loader
│   ├── brain/               # Multi-model orchestrator
│   │   ├── planner.py       # Step decomposition and diff reviewer
│   │   ├── coder.py         # Code and patch generator
│   │   └── router.py        # Task complexity classifier
│   ├── engine/              # Autonomous execution loop
│   │   ├── loop.py          # State machine and retry engine
│   │   ├── memory.py        # Context budgeting and compaction
│   │   └── safety.py        # Permission gate and command filter
│   ├── providers/           # LLM API and local runtime connectors
│   │   ├── ollama.py        # Ollama local inference driver
│   │   └── huggingface.py   # Hugging Face Inference Providers API
│   ├── merge/               # Model merging and quantization
│   │   ├── mergekit.py      # SLERP / TIES config generator
│   │   ├── quantize.py      # llama.cpp GGUF converter
│   │   └── bench.py         # Verification and benchmark runner
│   ├── tools/               # Agent workspace capabilities
│   │   ├── files.py         # File read and write operations
│   │   ├── diff.py          # Unified diff parser and patcher
│   │   ├── shell.py         # Sandboxed process execution
│   │   ├── git.py           # Git status, checkout, and commit
│   │   ├── search.py        # AST indexer and symbol lookup
│   │   └── tests.py         # Pytest discovery and runner
│   └── ui/                  # Rich terminal user interface
│       ├── terminal.py      # Streaming renderer and color theme
│       └── prompt.py        # Interactive input and confirmation prompts
├── tests/                   # Automated pytest suite
├── .gitignore               # Ignored cache, models, and virtualenvs
├── LICENSE                  # Apache 2.0 license declaration
└── README.md                # Project documentation and visual architecture
```
Codebase hierarchy separating multi-model intelligence, provider drivers, and sandboxed tooling.

---

## 🚀 Quickstart

```bash
# 1. Install Lathe in your environment
pip install lathe-agent

# 2. Pull local coder model via Ollama
ollama pull hf.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M

# 3. Configure Hugging Face token for router & reasoning API (optional)
export HF_TOKEN="hf_your_token_here"

# 4. Launch Lathe in any project workspace
lathe "Add JWT bearer auth & token rate limiter to auth/middleware.py"
```
Four simple steps to initialize your environment and launch an autonomous coding session.

---

## 🤝 Contributing & License

<div align="center">

[![License Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg?style=for-the-badge)](LICENSE)
[![GitHub Issues](https://img.shields.io/badge/Issues-PRs%20Welcome-brightgreen.svg?style=for-the-badge)](https://github.com)
[![Code of Conduct](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg?style=for-the-badge)](CODE_OF_CONDUCT.md)

</div>

Distributed under the Apache 2.0 License. Built openly with the open-source AI community.
