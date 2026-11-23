# Hugging Face Setup

Lathe integrates natively with Hugging Face for remote inference, token downloads, architecture compatibility checks, and publishing merged models.

---

## Setting Up Your Hugging Face Token

Lathe strictly isolates API secrets to environment variables to ensure tokens are never saved to project files or leaked in git commits.

### Step 1: Obtain an Access Token
1. Go to [Hugging Face Settings > Tokens](https://huggingface.co/settings/tokens).
2. Create a token:
   - **Read token**: Sufficient for architecture compatibility checks and remote inference.
   - **Write token**: Required if pushing merged weights via `lathe merge push <name>`.

### Step 2: Set the Token in Your Environment

**macOS / Linux:**
```bash
export HF_TOKEN="hf_your_secret_token_here"
```

To persist across terminal sessions, add the export to your shell configuration (`~/.zshrc` or `~/.bashrc`).

**Windows PowerShell:**
```powershell
$env:HF_TOKEN = "hf_your_secret_token_here"
```

---

## Hugging Face Inference Providers API

You can configure any role (coder, planner, or router) to utilize cloud models via Hugging Face's serverless Inference Providers API in `lathe.toml`:

```toml
[roles.coder]
backend = "huggingface"
model = "Qwen/Qwen2.5-Coder-32B-Instruct"
temperature = 0.0
max_tokens = 4096
context_window = 32768
```

Supported serverless providers are queried automatically based on latency and availability.

---

## Model Architecture Pre-Checks

When performing model merges with `lathe merge`, Lathe communicates with the Hugging Face Hub using `huggingface_hub` to fetch and validate model specifications without downloading multi-gigabyte weight tensors.

It verifies:
- `model_type` compatibility (e.g. `qwen2` matching `qwen2`)
- `hidden_size` matching across both models
- `num_hidden_layers` alignment
- `vocab_size` and tokenizer compatibility

Pairs with mismatched architectures are refused before downloading weights.

---

## Publishing Merged Weights

Once a model is merged into `merges/<name>`, you can upload it directly to your Hugging Face account:

```bash
lathe merge push my-merged-coder
```

By default, repositories are created with **private visibility** unless you explicitly confirm public release.
