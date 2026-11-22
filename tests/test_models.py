"""Tests for lathe.models: searching, pulling, probing, local listing, and RAM checks."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from lathe.cli import app
from lathe.config import LatheConfig, RoleConfig
from lathe.llm.factory import get_client
from lathe.models.capabilities import (
    get_capability,
    load_capabilities,
    save_capability,
)
from lathe.models.local import _models_match, get_local_ollama_models
from lathe.models.probe import probe_model
from lathe.models.pull import normalize_ollama_model_name, pull_model_stream
from lathe.models.ram import format_bytes, get_available_ram_bytes
from lathe.models.search import extract_quant, search_gguf_repos

runner = CliRunner()


# --- RAM & Byte Formatting Tests ---


def test_format_bytes() -> None:
    """format_bytes must format various byte counts accurately."""
    assert format_bytes(0) == "0 B"
    assert format_bytes(500) == "500 B"
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(1024 * 1024) == "1.00 MB"
    assert format_bytes(4683073536) == "4.36 GB"


def test_get_available_ram_bytes() -> None:
    """get_available_ram_bytes must return an integer or None on unsupported OS."""
    ram = get_available_ram_bytes()
    if ram is not None:
        assert isinstance(ram, int)
        assert ram > 0


# --- Capabilities Cache Tests ---


def test_capabilities_cache(tmp_path: Path) -> None:
    """Capabilities must save, load, and lookup with prefix normalization."""
    cap_file = tmp_path / "capabilities.json"
    assert load_capabilities(cap_file) == {}

    save_capability("bartowski/model:Q4_K_M", "json_fallback", path=cap_file)
    caps = load_capabilities(cap_file)
    assert "bartowski/model:Q4_K_M" in caps
    assert caps["bartowski/model:Q4_K_M"]["tool_protocol"] == "json_fallback"
    assert caps["bartowski/model:Q4_K_M"]["supports_tools"] is False

    # Lookups should match both prefixed and unprefixed
    res1 = get_capability("bartowski/model:Q4_K_M", path=cap_file)
    assert res1 is not None and res1["tool_protocol"] == "json_fallback"

    res2 = get_capability("hf.co/bartowski/model:Q4_K_M", path=cap_file)
    assert res2 is not None and res2["tool_protocol"] == "json_fallback"


# --- Search & Quant Extraction Tests ---


@dataclass
class MockSibling:
    rfilename: str
    size: int


@dataclass
class MockModelInfo:
    siblings: list[MockSibling]


@dataclass
class MockHubModel:
    id: str
    downloads: int = 1500
    likes: int = 42
    last_modified: str = "2026-11-20"


class MockHfApi:
    """Mock Hugging Face API returning controlled model and file info."""

    def __init__(
        self,
        models: list[MockHubModel],
        files_by_repo: dict[str, list[MockSibling]],
    ) -> None:
        self._models = models
        self._files = files_by_repo

    def list_models(self, **kwargs: Any) -> list[MockHubModel]:
        return self._models

    def model_info(self, repo_id: str, **kwargs: Any) -> MockModelInfo:
        return MockModelInfo(siblings=self._files.get(repo_id, []))


def test_extract_quant() -> None:
    """extract_quant must accurately detect Q4_K_M, Q5_K_M, and Q8_0."""
    assert extract_quant("model-q4_k_m.gguf") == "Q4_K_M"
    assert extract_quant("model.Q8_0.gguf") == "Q8_0"
    assert extract_quant("model-q5_k_m-00001-of-00002.gguf") == "Q5_K_M"
    assert extract_quant("readme.md") is None


def test_search_gguf_repos_with_mock() -> None:
    """search_gguf_repos must group single files and aggregate sharded files."""
    mock_models = [
        MockHubModel(id="test/model-7b", downloads=5000, likes=120),
    ]
    mock_files = {
        "test/model-7b": [
            MockSibling(rfilename="model-q4_k_m.gguf", size=4_000_000_000),
            MockSibling(rfilename="model-q8_0-00001-of-00002.gguf", size=4_000_000_000),
            MockSibling(rfilename="model-q8_0-00002-of-00002.gguf", size=4_000_000_000),
        ]
    }
    api = MockHfApi(models=mock_models, files_by_repo=mock_files)
    results = search_gguf_repos("test", limit=5, api=api)

    assert len(results) == 1
    r = results[0]
    assert r.id == "test/model-7b"
    assert r.downloads == 5000
    assert r.quants["Q4_K_M"] == 4_000_000_000
    # Sharded Q8_0 summed
    assert r.quants["Q8_0"] == 8_000_000_000


# --- Model Normalization & Pull Tests ---


def test_normalize_ollama_model_name() -> None:
    """normalize_ollama_model_name must format all repo strings into hf.co syntax."""
    assert (
        normalize_ollama_model_name("bartowski/Qwen2.5-Coder-7B-Instruct-GGUF")
        == "hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M"
    )
    assert (
        normalize_ollama_model_name("bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q8_0")
        == "hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q8_0"
    )
    assert normalize_ollama_model_name("hf.co/user/repo:Q5_K_M") == "hf.co/user/repo:Q5_K_M"
    assert normalize_ollama_model_name("llama3.2:3b") == "llama3.2:3b"


@pytest.mark.asyncio
async def test_pull_model_stream() -> None:
    """pull_model_stream must parse streaming events from Ollama."""
    lines = [
        json.dumps({"status": "pulling manifest"}) + "\n",
        json.dumps({"status": "downloading", "total": 100, "completed": 50}) + "\n",
        json.dumps({"status": "success"}) + "\n",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/api/pull")
        return httpx.Response(200, content="".join(lines).encode("utf-8"))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    events = [e async for e in pull_model_stream("hf.co/test/model:Q4_K_M", client=client)]

    assert len(events) == 3
    assert events[0]["status"] == "pulling manifest"
    assert events[1]["completed"] == 50
    assert events[2]["status"] == "success"


# --- Probe Tool Support Tests ---


@pytest.mark.asyncio
async def test_probe_native_tool_support(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """probe_model must identify native tool support when Ollama returns tool_calls."""
    cap_file = tmp_path / "capabilities.json"
    monkeypatch.setattr("lathe.models.capabilities.get_capabilities_file_path", lambda: cap_file)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("tools"):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {"function": {"name": "add", "arguments": {"a": 2, "b": 3}}}
                        ],
                    }
                },
            )
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "hello"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    protocol = await probe_model("test-model", client=client)

    assert protocol == "native"
    assert get_capability("test-model", path=cap_file)["tool_protocol"] == "native"


@pytest.mark.asyncio
async def test_probe_json_fallback_support(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """probe_model must identify json_fallback when model produces Markdown JSON code block."""
    cap_file = tmp_path / "capabilities.json"
    monkeypatch.setattr("lathe.models.capabilities.get_capabilities_file_path", lambda: cap_file)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": '```json\n{"name": "add", "arguments": {"a": 2, "b": 3}}\n```',
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    protocol = await probe_model("test-fallback-model", client=client)

    assert protocol == "json_fallback"
    assert get_capability("test-fallback-model", path=cap_file)["tool_protocol"] == "json_fallback"


# --- Local Models Listing & Role Matching ---


@pytest.mark.asyncio
async def test_get_local_ollama_models() -> None:
    """get_local_ollama_models must correlate installed models with active roles."""
    mock_tags = {
        "models": [
            {
                "name": "hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M",
                "size": 4_683_076_387,
                "modified_at": "2026-11-22T10:00:00Z",
            },
            {
                "name": "llama3.2:1b",
                "size": 1_000_000_000,
                "modified_at": "2026-11-22T09:00:00Z",
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_tags)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = LatheConfig(
        roles={
            "coder": RoleConfig(
                backend="ollama",
                model="hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M",
            ),
            "router": RoleConfig(backend="ollama", model="llama3.2:1b"),
        }
    )

    results = await get_local_ollama_models(client=client, config=cfg)
    assert len(results) == 2
    assert "coder" in results[0]["roles"]
    assert "router" in results[1]["roles"]


def test_models_match() -> None:
    """_models_match must handle case and hf.co prefix differences."""
    assert _models_match("hf.co/user/model:q4", "user/model:q4") is True
    assert _models_match("user/model:q4", "hf.co/user/model:q4") is True
    assert _models_match("modelA", "modelB") is False


# --- Factory Integration Tests ---


def test_factory_picks_cached_capability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM factory must read cached capabilities to configure supports_tools automatically."""
    cap_file = tmp_path / "capabilities.json"
    save_capability("qwen-test", "json_fallback", path=cap_file)
    monkeypatch.setattr("lathe.models.capabilities.get_capabilities_file_path", lambda: cap_file)

    cfg = LatheConfig(
        roles={
            "coder": RoleConfig(
                backend="ollama",
                model="qwen-test",
                supports_tools=True,  # Default was True
            )
        }
    )

    client = get_client("coder", config=cfg)
    # The factory should have automatically updated supports_tools to False!
    assert client.role_config.supports_tools is False


# --- CLI Commands Integration Tests ---


def test_cli_models_use_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """lathe models use <role> <model> must update lathe.toml."""
    config_file = tmp_path / "lathe.toml"
    config_file.write_text("[roles.coder]\nbackend = 'ollama'\nmodel = 'old-model'\n")
    monkeypatch.setattr("lathe.models.cli.get_project_config_path", lambda: config_file)

    res = runner.invoke(app, ["models", "use", "coder", "new-coder:7b"])
    assert res.exit_code == 0
    assert "Successfully updated" in res.stdout
    assert "new-coder:7b" in config_file.read_text()


def test_cli_models_list_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """lathe models list command renders the local models table."""

    async def mock_list() -> list[dict[str, Any]]:
        return [
            {
                "name": "hf.co/bartowski/Qwen2.5-Coder-7B:Q4_K_M",
                "size": 4_000_000_000,
                "size_formatted": "3.72 GB",
                "modified_at": "2026-11-22T11:00:00",
                "roles": ["coder"],
            }
        ]

    monkeypatch.setattr("lathe.models.cli.get_local_ollama_models", mock_list)
    res = runner.invoke(app, ["models", "list"])
    assert res.exit_code == 0
    assert "Local Ollama Models" in res.stdout
    assert "Qwen2.5-Coder-7B" in res.stdout
    assert "coder" in res.stdout
