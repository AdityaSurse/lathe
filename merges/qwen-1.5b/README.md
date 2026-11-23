---
license: apache-2.0
tags:
  - merge
  - mergekit
  - lathe
  - open-weights
base_model:
  - Qwen/Qwen2.5-Coder-1.5B
  - Qwen/Qwen2.5-1.5B-Instruct
---

# qwen-1.5b

`qwen-1.5b` is an open-source model merge produced with [Lathe](https://github.com/lathe-agent/lathe)
using [mergekit](https://github.com/arcee-ai/mergekit).

## Source Models

The following parent models were merged into this checkpoint:
- [Qwen/Qwen2.5-Coder-1.5B](https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B)
- [Qwen/Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct)

## Merge Configuration

- **Method**: `slerp`
- **Precision**: `float16`
- **Parameters**:
```json
{
  "t": 0.5
}
```

### mergekit YAML Config

```yaml
slices:
- sources:
  - model: Qwen/Qwen2.5-Coder-1.5B
    layer_range: [0, 28]
  - model: Qwen/Qwen2.5-1.5B-Instruct
    layer_range: [0, 28]
merge_method: slerp
base_model: Qwen/Qwen2.5-Coder-1.5B
parameters: {t: 0.5}
dtype: float16
```

## Local Inference & Deployment

This merged safetensors checkpoint can be quantized to GGUF format via `llama.cpp`
and deployed locally to Ollama:

1. **Convert to GGUF**:
   ```bash
   python3 llama.cpp/convert_hf_to_gguf.py merges/qwen-1.5b --outtype f16 --outfile qwen-1.5b.fp16.gguf
   ```

2. **Quantize to Q4_K_M**:
   ```bash
   ./llama-quantize qwen-1.5b.fp16.gguf qwen-1.5b.Q4_K_M.gguf Q4_K_M
   ```

3. **Serve with Ollama**:
   ```bash
   ollama create qwen-1.5b -f Modelfile
   ollama run qwen-1.5b
   ```
