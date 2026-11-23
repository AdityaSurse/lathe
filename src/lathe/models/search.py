"""Search Hugging Face Hub for GGUF model repositories and extract quant file metadata."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

TARGET_QUANTS = ["Q4_K_M", "Q5_K_M", "Q8_0"]


@dataclass
class GGUFRepoResult:
    """Represents a discovered GGUF model repository on Hugging Face."""

    id: str
    downloads: int
    likes: int
    last_modified: str
    quants: dict[str, int]


def extract_quant(filename: str) -> str | None:
    """Extract standard quantization format tag from GGUF filename."""
    fn = filename.lower()
    for q in TARGET_QUANTS:
        ql = q.lower()
        pattern = r"[-._]" + re.escape(ql) + r"([-._]|\.gguf)"
        if re.search(pattern, fn):
            return q
    return None


def search_gguf_repos(
    query: str,
    limit: int = 5,
    token: str | None = None,
    api: Any | None = None,
) -> list[GGUFRepoResult]:
    """Search Hugging Face Hub for GGUF models, sorting by downloads."""
    from huggingface_hub import HfApi

    client = api or HfApi(token=token)
    results: list[GGUFRepoResult] = []

    try:
        models = client.list_models(
            search=query,
            filter="gguf",
            sort="downloads",
            limit=limit,
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to query Hugging Face Hub: {exc}") from exc

    for m in models:
        repo_id = str(m.id)
        downloads = int(getattr(m, "downloads", 0) or 0)
        likes = int(getattr(m, "likes", 0) or 0)
        last_mod = getattr(m, "last_modified", None)
        if isinstance(last_mod, datetime):
            last_mod_str = last_mod.strftime("%Y-%m-%d")
        elif last_mod:
            last_mod_str = str(last_mod)[:10]
        else:
            last_mod_str = "Unknown"

        quants: dict[str, int] = {}
        try:
            info = client.model_info(repo_id, files_metadata=True)
            siblings = getattr(info, "siblings", []) or []
            single_files: dict[str, int] = {}
            shards: dict[str, int] = {}

            for s in siblings:
                rfilename = getattr(s, "rfilename", "") or ""
                size = getattr(s, "size", 0) or 0
                if not rfilename.lower().endswith(".gguf"):
                    continue

                q = extract_quant(rfilename)
                if not q:
                    continue

                if "-of-" in rfilename.lower() or ".part" in rfilename.lower():
                    shards[q] = shards.get(q, 0) + size
                else:
                    single_files[q] = size

            for target in TARGET_QUANTS:
                if target in single_files:
                    quants[target] = single_files[target]
                elif target in shards:
                    quants[target] = shards[target]
        except Exception:
            pass

        results.append(
            GGUFRepoResult(
                id=repo_id,
                downloads=downloads,
                likes=likes,
                last_modified=last_mod_str,
                quants=quants,
            )
        )

    return results
