# Model Merging

Lathe includes a complete model combination and conversion pipeline powered by `mergekit` and `llama.cpp`. It allows developers to create custom hybrid models (e.g. combining a code specialist with an instruction-following model) and run them locally.

---

## The `lathe merge` Wizard

Launch the interactive wizard:

```bash
lathe merge
```

### 1. Selecting Candidate Models
Choose two Hugging Face safetensors repositories. You can pick popular presets or specify custom repository IDs:
- **Preset (Laptops)**: `Qwen/Qwen2.5-Coder-1.5B` + `Qwen/Qwen2.5-1.5B-Instruct`
- **Custom (Workstations)**: `Qwen/Qwen2.5-Coder-7B` + `deepseek-ai/DeepSeek-R1-Distill-Qwen-7B`

*(Note: Hugging Face safetensors repos are required; GGUF repositories cannot be merged directly).*

### 2. Architecture Compatibility Pre-Check
Before downloading weights (saving gigabytes of bandwidth and disk space), Lathe queries the Hugging Face Hub using `huggingface_hub` to verify architecture compatibility:
- `model_type` (must match, e.g. `qwen2`)
- `hidden_size`
- `num_hidden_layers`
- `vocab_size` and tokenizer configuration

If architectures diverge, Lathe displays a formatted table highlighting differences and halts safely.

### 3. Choosing Merge Method
- **SLERP (Spherical Linear Interpolation)**: Recommended for combining two fine-tuned models derived from the same base. Supports interpolation parameter $t \in [0, 1]$ and per-layer gradients.
- **TIES (Trim, Elect Sign & Merge)**: Resolves parameter interference by trimming small magnitude deltas and electing unanimous parameter signs.
- **DARE-TIES**: Drop And REscale variant of TIES preserving base model generalization.
- **Linear**: Simple weighted arithmetic average of model weights.

### 4. Hardware Estimation
Lathe calculates parameters and required memory ($\text{params} \times 2 \text{ bytes}$ for FP16), inspects available RAM and disk space, and warns if resources are constrained.

---

## Local Execution vs Google Colab

### Running Locally
Lathe generates the configuration into `merges/<name>/config.yaml` and executes `mergekit-yaml` using lazy unpickling and low-memory CPU options:

```bash
lathe merge --name my-custom-merge
```

### Running in Google Colab (`--colab`)
If your local machine lacks sufficient RAM or GPU compute, pass `--colab` to generate a self-contained Google Colab notebook (`.ipynb`):

```bash
lathe merge --colab --name my-colab-merge
```

The notebook configures GPU runtime, installs `mergekit`, executes the merge, and uploads results directly to your Hugging Face Hub account.

---

## GGUF Quantization & Ollama Deployment

Once your model is merged into `merges/<name>`, convert and quantize it for instant local inference in Ollama:

```bash
lathe merge gguf my-custom-merge --quant Q4_K_M
```

This automated step:
1. Clones and compiles `llama.cpp` in `~/.cache/lathe/llama.cpp` (pinned to a stable release).
2. Converts safetensors to FP16 GGUF using `convert_hf_to_gguf.py`.
3. Quantizes weights using `llama-quantize` to your target format (default `Q4_K_M`).
4. Generates an Ollama `Modelfile` preserving the parent model's exact Jinja chat template.
5. Runs `ollama create lathe-my-custom-merge -f Modelfile`.
6. Calibrates tool calling with `lathe models probe lathe-my-custom-merge`.
