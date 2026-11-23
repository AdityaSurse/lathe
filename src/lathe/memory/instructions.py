"""Project instruction file management (LATHE.md) and repository exploration."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from lathe.config import get_global_config_path
from lathe.llm.base import LLMClient
from lathe.llm.types import Message
from lathe.tools.tests import detect_test_command


def get_global_lathe_md_path() -> Path:
    """Return default global project instruction file path (~/.config/lathe/LATHE.md)."""
    return get_global_config_path().parent / "LATHE.md"


def get_local_lathe_md_path(workspace_root: Path | str | None = None) -> Path:
    """Return project root instruction file path (<workspace_root>/LATHE.md)."""
    base = Path(workspace_root) if workspace_root is not None else Path.cwd()
    return base.resolve() / "LATHE.md"


def load_project_instructions(workspace_root: Path | str | None = None) -> str:
    """Load and combine global and local LATHE.md instructions for system prompt injection.

    Returns empty string if neither file exists.
    """
    sections: list[str] = []

    # 1. Global instructions (~/.config/lathe/LATHE.md)
    global_path = get_global_lathe_md_path()
    try:
        if global_path.is_file():
            content = global_path.read_text(encoding="utf-8").strip()
            if content:
                sections.append(f"## Global User Guidelines (~/.config/lathe/LATHE.md)\n{content}")
    except OSError:
        pass

    # 2. Local repository instructions (<workspace_root>/LATHE.md)
    local_path = get_local_lathe_md_path(workspace_root)
    try:
        if local_path.is_file():
            content = local_path.read_text(encoding="utf-8").strip()
            if content:
                sections.append(f"## Project Instructions (LATHE.md)\n{content}")
    except OSError:
        pass

    if not sections:
        return ""

    header = (
        "# Project Guidelines & Memory (LATHE.md)\n"
        "The following project instructions and user preferences must be strictly followed:\n"
    )
    return f"{header}\n" + "\n\n".join(sections)


def append_to_lathe_md(fact: str, workspace_root: Path | str | None = None) -> Path:
    """Append a fact or instruction to LATHE.md under the '## Notes' section.

    If LATHE.md does not exist, creates it with a starter template.
    If '## Notes' does not exist, appends the section heading.
    """
    target_path = get_local_lathe_md_path(workspace_root)
    clean_fact = fact.strip()
    bullet_item = clean_fact if clean_fact.startswith("- ") else f"- {clean_fact}"

    if not target_path.exists():
        initial_content = (
            "# Project Instructions (LATHE.md)\n\n"
            "Project guidelines, architectural rules, and operational notes.\n\n"
            "## Notes\n"
            f"{bullet_item}\n"
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(initial_content, encoding="utf-8")
        return target_path

    content = target_path.read_text(encoding="utf-8")

    # Match existing '## Notes' section header (case-insensitive)
    notes_match = re.search(r"^##\s+notes\b", content, re.IGNORECASE | re.MULTILINE)

    if notes_match:
        start_idx = notes_match.end()
        # Find next heading (e.g. ^## ) or EOF
        next_heading = re.search(r"^##\s+", content[start_idx:], re.MULTILINE)
        if next_heading:
            insert_pos = start_idx + next_heading.start()
            section_body = content[start_idx:insert_pos].rstrip()
            updated_section = f"{section_body}\n{bullet_item}\n\n"
            new_content = content[:start_idx] + updated_section + content[insert_pos:]
        else:
            new_content = content.rstrip() + f"\n{bullet_item}\n"
    else:
        new_content = content.rstrip() + f"\n\n## Notes\n{bullet_item}\n"

    target_path.write_text(new_content, encoding="utf-8")
    return target_path


def explore_repository(workspace_root: Path | str | None = None) -> dict[str, Any]:
    """Examine workspace structure, key configuration files, and detected tech stack."""
    ws = Path(workspace_root).resolve() if workspace_root is not None else Path.cwd()

    summary: dict[str, Any] = {
        "workspace": str(ws),
        "name": ws.name,
        "languages": [],
        "frameworks": [],
        "key_files": [],
        "test_command": detect_test_command(ws),
        "repomap_summary": "",
    }

    # Detect key configuration files
    check_files = [
        ("pyproject.toml", "Python (pyproject.toml)"),
        ("setup.py", "Python (setup.py)"),
        ("requirements.txt", "Python (requirements.txt)"),
        ("Pipfile", "Python (Pipfile)"),
        ("package.json", "Node/JS/TS (package.json)"),
        ("tsconfig.json", "TypeScript (tsconfig.json)"),
        ("Cargo.toml", "Rust (Cargo.toml)"),
        ("go.mod", "Go (go.mod)"),
        ("Makefile", "Makefile"),
        ("CMakeLists.txt", "C/C++ (CMake)"),
        ("pom.xml", "Java (Maven)"),
        ("build.gradle", "Java/Kotlin (Gradle)"),
        ("Dockerfile", "Docker"),
        ("docker-compose.yml", "Docker Compose"),
        ("lathe.toml", "Lathe Agent Config"),
        ("README.md", "README Documentation"),
    ]

    for fname, label in check_files:
        fpath = ws / fname
        if fpath.is_file():
            summary["key_files"].append(label)
            if "Python" in label and "Python" not in summary["languages"]:
                summary["languages"].append("Python")
            elif "Node" in label or "TypeScript" in label:
                if "JavaScript/TypeScript" not in summary["languages"]:
                    summary["languages"].append("JavaScript/TypeScript")
            elif "Rust" in label and "Rust" not in summary["languages"]:
                summary["languages"].append("Rust")
            elif "Go" in label and "Go" not in summary["languages"]:
                summary["languages"].append("Go")
            elif "C/C++" in label and "C/C++" not in summary["languages"]:
                summary["languages"].append("C/C++")
            elif "Java" in label and "Java" not in summary["languages"]:
                summary["languages"].append("Java")

    # Inspect file extensions across repository (top-level and 1st depth)
    extension_map = {
        ".py": "Python",
        ".ts": "TypeScript",
        ".tsx": "TypeScript (React)",
        ".js": "JavaScript",
        ".jsx": "JavaScript (React)",
        ".rs": "Rust",
        ".go": "Go",
        ".c": "C",
        ".cpp": "C++",
        ".h": "C/C++ Header",
        ".java": "Java",
        ".rb": "Ruby",
        ".php": "PHP",
    }

    try:
        for p in ws.glob("*.*"):
            lang = extension_map.get(p.suffix.lower())
            if lang and lang not in summary["languages"]:
                summary["languages"].append(lang)
    except Exception:
        pass

    # Extract brief repo map signatures if RepoMap is available
    try:
        from lathe.context.repomap import RepoMap

        rm = RepoMap(workspace_root=ws, token_budget=1024)
        map_text = rm.get_repo_map()
        if map_text:
            lines = [line for line in map_text.splitlines() if line.strip()]
            summary["repomap_summary"] = "\n".join(lines[:30])
    except Exception:
        pass

    return summary


def generate_initial_lathe_md(
    workspace_root: Path | str | None = None,
    client: LLMClient | None = None,
) -> str:
    """Generate a first LATHE.md instruction file based on repository analysis."""
    ws = Path(workspace_root).resolve() if workspace_root is not None else Path.cwd()
    analysis = explore_repository(ws)

    # If client is provided, query the LLM to draft instructions
    if client is not None:
        try:
            return _generate_lathe_md_with_llm(client, ws, analysis)
        except Exception:
            pass

    # Deterministic fallback synthesis
    return _generate_lathe_md_fallback(ws, analysis)


def _generate_lathe_md_with_llm(
    client: LLMClient,
    workspace_root: Path,
    analysis: dict[str, Any],
) -> str:
    """Prompt an LLM to generate comprehensive LATHE.md instructions."""
    import asyncio

    test_cmd = analysis.get("test_command") or "pytest (or appropriate runner)"
    languages = ", ".join(analysis.get("languages", [])) or "Detected codebase"
    key_files = ", ".join(analysis.get("key_files", [])) or "Standard project files"

    prompt = (
        f"You are initializing LATHE.md for the repository '{analysis['name']}'.\n\n"
        f"- Languages: {languages}\n"
        f"- Key Files: {key_files}\n"
        f"- Test Command: {test_cmd}\n\n"
        "Generate a clear, concise LATHE.md adhering strictly to this markdown structure:\n"
        "# Project Instructions (LATHE.md)\n"
        "## Tech Stack\n"
        "## How to Run\n"
        "## How to Test\n"
        "## Code Conventions\n"
        "## Notes\n\n"
        "Return ONLY the markdown document without additional commentary."
    )

    messages = [
        Message(
            role="system",
            content="You generate precise developer instructions for LATHE.md.",
        ),
        Message(role="user", content=prompt),
    ]

    async def _call() -> str:
        parts: list[str] = []
        async for chunk in client.chat(messages, stream=True):
            if chunk.delta:
                parts.append(chunk.delta)
        return "".join(parts).strip()

    result = asyncio.run(_call())
    if result.startswith("```"):
        # Strip markdown fences if LLM wrapped it
        lines = result.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
            result = "\n".join(lines[1:-1]).strip()

    if "# Project Instructions" in result:
        return result

    return _generate_lathe_md_fallback(workspace_root, analysis)


def _generate_lathe_md_fallback(
    workspace_root: Path,
    analysis: dict[str, Any],
) -> str:
    """Synthesize clean, deterministic LATHE.md when LLM generation is unavailable."""
    name = analysis.get("name", workspace_root.name)
    languages = analysis.get("languages", [])
    lang_str = ", ".join(languages) if languages else "Multi-language project"
    test_cmd = analysis.get("test_command") or "(auto-detected test runner)"
    key_files = analysis.get("key_files", [])

    # Infer how to run / install based on key files
    how_to_run_lines = []
    if any("pyproject.toml" in f or "requirements.txt" in f for f in key_files):
        how_to_run_lines.append("- Install dependencies: `pip install -e .` or `uv sync`")
        module_name = name.lower().replace("-", "_")
        how_to_run_lines.append(f"- Run CLI or entrypoint: `python -m {module_name}`")
    elif any("package.json" in f for f in key_files):
        how_to_run_lines.append("- Install dependencies: `npm install` (or `pnpm install`)")
        how_to_run_lines.append("- Start dev server / app: `npm start` or `npm run dev`")
    elif any("Cargo.toml" in f for f in key_files):
        how_to_run_lines.append("- Build project: `cargo build`")
        how_to_run_lines.append("- Run binary: `cargo run`")
    elif any("go.mod" in f for f in key_files):
        how_to_run_lines.append("- Build project: `go build ./...`")
        how_to_run_lines.append("- Run main: `go run .`")
    else:
        how_to_run_lines.append("- Refer to project README.md for startup instructions.")

    how_to_run_text = "\n".join(how_to_run_lines)

    conventions = [
        "- Read files before editing; make minimal, targeted modifications.",
        "- Never guess file contents or function signatures.",
        "- Follow established code formatting and strict type annotations.",
        "- Always run verification tests before completing tasks.",
    ]
    conventions_text = "\n".join(conventions)

    return (
        "# Project Instructions (LATHE.md)\n\n"
        f"Operational guidelines and conventions for `{name}`.\n\n"
        "## Tech Stack\n"
        f"- Primary Languages: {lang_str}\n"
        f"- Detected Key Files: {', '.join(key_files) if key_files else 'Standard repository'}\n\n"
        "## How to Run\n"
        f"{how_to_run_text}\n\n"
        "## How to Test\n"
        f"- Test Command: `{test_cmd}`\n\n"
        "## Code Conventions\n"
        f"{conventions_text}\n\n"
        "## Notes\n"
        "- Initialized with `/init`.\n"
    )
