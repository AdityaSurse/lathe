# Choosing Models

Lathe divides agent execution across four specialized roles: **Coder**, **Planner**, **Reviewer**, and **Router**. Selecting appropriate models for your hardware configuration optimizes latency, throughput, and accuracy.

---

## Role Responsibilities

| Role | Responsibility | Ideal Model Characteristics | Recommended Local Model |
|---|---|---|---|
| **Coder** | Inspects files, produces targeted unified diffs, runs test suites, executes shell tools. | Strong syntax adherence, high coding benchmark score, reliable function calling. | `qwen2.5-coder:7b` or `qwen2.5-coder:1.5b` |
| **Planner** | Deconstructs complex tasks, synthesizes repository maps, writes structured JSON execution steps. | Deep chain-of-thought reasoning, strong architectural planning. | `deepseek-r1:8b` or `deepseek-r1:7b` |
| **Reviewer** | Evaluates coder step diffs and test results against Lathe's review rubric. | Critical code audit skills, bug detection, schema validation. | Defaults to Planner (`deepseek-r1:8b`) |
| **Router** | Classifies incoming developer messages into `chat`, `simple`, or `complex`, writes compaction summaries. | Lightweight, high throughput, low latency. | `qwen2.5-coder:1.5b` or `qwen2.5:1.5b` |

---

## Recommended Hardware Configurations

### Tier 1: Laptop (8 GB - 16 GB Unified Memory / RAM)
- **Coder**: `qwen2.5-coder:1.5b` (Q4_K_M ~1.0 GB RAM)
- **Planner**: `deepseek-r1:1.5b` or `qwen2.5-coder:7b`
- **Router**: `qwen2.5-coder:1.5b`

```bash
ollama pull qwen2.5-coder:1.5b
ollama pull deepseek-r1:1.5b
```

### Tier 2: Workstation (16 GB - 32 GB RAM or VRAM)
- **Coder**: `qwen2.5-coder:7b` (Q4_K_M ~4.7 GB RAM)
- **Planner**: `deepseek-r1:8b` (Q4_K_M ~4.9 GB RAM)
- **Router**: `qwen2.5-coder:1.5b`

```bash
ollama pull qwen2.5-coder:7b
ollama pull deepseek-r1:8b
ollama pull qwen2.5-coder:1.5b
```

### Tier 3: High-End Workstation (32 GB - 64 GB+ RAM or VRAM)
- **Coder**: `qwen2.5-coder:14b` or `qwen2.5-coder:32b`
- **Planner**: `deepseek-r1:14b` or `deepseek-r1:32b`
- **Router**: `qwen2.5-coder:7b`

---

## Calibrating Tool Calling with `lathe models probe`

Different GGUF quantizations handle tool calling via either native function calling or fallback `<tool_call>` parsing. Run the automatic probe utility to test your model's capabilities:

```bash
lathe models probe qwen2.5-coder:7b
```

Lathe will run a sample tool call against the model, determine whether native or fallback schema parsing performs reliably, and cache the preferred protocol in `.lathe/models_cache.json`.
