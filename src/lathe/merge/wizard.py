"""Interactive CLI wizard guiding model selection, compatibility checks, and mergekit."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax

from lathe.merge.colab import generate_colab_notebook
from lathe.merge.compatibility import (
    check_compatibility,
    fetch_model_info,
    render_compatibility_table,
)
from lathe.merge.generator import generate_merge_yaml, write_merge_config
from lathe.merge.models import (
    START_SMALL_PRESET,
    MergeMethod,
    MergePreset,
)
from lathe.merge.resources import estimate_merge_resources, render_resource_table
from lathe.merge.runner import (
    is_mergekit_installed,
    run_mergekit,
    write_model_card,
)

console = Console()


def run_merge_wizard(
    colab: bool = False,
    name: str | None = None,
    preset: bool = False,
    interactive: bool = True,
    out_console: Console | None = None,
) -> None:
    """Run the step-by-step interactive model merge wizard."""
    out = out_console or console
    is_interactive = interactive and sys.stdin.isatty()

    out.print(
        Panel(
            "[bold white]Lathe Model Merging Wizard[/bold white]\n"
            "[dim]Architecture compatibility verification and mergekit YAML generation.[/dim]",
            border_style="bright_blue",
            title="[bold cyan]lathe merge[/bold cyan]",
        )
    )

    # 1. Preset or custom models
    chosen_preset: MergePreset | None = None
    if preset or not is_interactive:
        chosen_preset = START_SMALL_PRESET
    else:
        out.print("\n[bold cyan]Step 1: Select Model Source[/bold cyan]")
        out.print(f"  [bold]1)[/bold] {START_SMALL_PRESET.description} [green](Preset)[/green]")
        out.print("  [bold]2)[/bold] Custom Hugging Face Model Checkpoints (safetensors)")
        choice = Prompt.ask("Choose an option", choices=["1", "2"], default="1")
        if choice == "1":
            chosen_preset = START_SMALL_PRESET

    if chosen_preset:
        model_a_id = chosen_preset.model_a
        model_b_id = chosen_preset.model_b
        default_name = chosen_preset.name
        method = chosen_preset.method
        base_model_id = chosen_preset.base_model
        params = dict(chosen_preset.default_parameters)
        out.print(f"\n[green]Using preset:[/green] {chosen_preset.name}")
        out.print(f"  • Model A: {model_a_id}")
        out.print(f"  • Model B: {model_b_id}")
    else:
        out.print(
            "\n[bold]Enter Hugging Face repository IDs (must be safetensors, not GGUF):[/bold]"
        )
        model_a_id = Prompt.ask("Model A Repository ID", default="Qwen/Qwen2.5-Coder-1.5B").strip()
        model_b_id = Prompt.ask(
            "Model B Repository ID", default="Qwen/Qwen2.5-1.5B-Instruct"
        ).strip()
        short_a = model_a_id.split("/")[-1].lower()
        short_b = model_b_id.split("/")[-1].lower()
        default_name = f"{short_a}-{short_b}-merge"
        base_model_id = model_a_id
        method = MergeMethod.SLERP
        params = {}

    merge_name = name or (
        Prompt.ask("\nEnter output name for this merge", default=default_name).strip()
        if is_interactive
        else default_name
    )

    # 2. Compatibility check BEFORE downloading weights
    out.print("\n[bold cyan]Step 2: Checking Model Architecture Compatibility...[/bold cyan]")
    try:
        model_a_info = fetch_model_info(model_a_id)
        model_b_info = fetch_model_info(model_b_id)
    except Exception as exc:
        out.print(f"[bold red]Failed to inspect model architectures:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    compat_result = check_compatibility(model_a_info, model_b_info)
    out.print(render_compatibility_table(compat_result))

    if not compat_result.is_compatible:
        out.print("\n[bold red]Refusing to merge incompatible models![/bold red]")
        for reason in compat_result.reasons:
            out.print(f"  [red]✗[/red] {reason}")
        out.print(
            "\n[yellow]Mergekit requires models with identical hidden dimensions, layer counts, "
            "and matching vocabulary matrices.[/yellow]"
        )
        raise typer.Exit(code=1)

    out.print("[bold green]✓ Architectures are compatible for weight interpolation.[/bold green]")

    # 3. Pick method (if custom models)
    if not chosen_preset:
        out.print("\n[bold cyan]Step 3: Select Merge Method[/bold cyan]")
        out.print(
            "  [bold]1)[/bold] SLERP (Spherical Linear Interpolation - recommended for 2 models)"
        )
        out.print("  [bold]2)[/bold] TIES (TrIm, Elect, and Merge - requires base model)")
        out.print("  [bold]3)[/bold] DARE-TIES (Drop And REscale with TIES - requires base model)")
        out.print("  [bold]4)[/bold] Linear (Simple weighted average)")

        method_choice = (
            Prompt.ask("Choose method", choices=["1", "2", "3", "4"], default="1")
            if is_interactive
            else "1"
        )
        if method_choice == "1":
            method = MergeMethod.SLERP
        elif method_choice == "2":
            method = MergeMethod.TIES
        elif method_choice == "3":
            method = MergeMethod.DARE_TIES
        else:
            method = MergeMethod.LINEAR

        if method == MergeMethod.SLERP:
            t_val = (
                float(
                    Prompt.ask(
                        "Interpolation parameter t (0.0=Model A, 1.0=Model B)", default="0.5"
                    )
                )
                if is_interactive
                else 0.5
            )
            use_gradient = (
                Confirm.ask("Apply layer-wise t gradient for self_attn vs mlp?", default=False)
                if is_interactive
                else False
            )
            self_attn_t = [0.0, 0.5, 0.7, 1.0] if use_gradient else None
            mlp_t = [1.0, 0.5, 0.3, 0.0] if use_gradient else None
            params = {"t": t_val, "self_attn_t": self_attn_t, "mlp_t": mlp_t}
        elif method in (MergeMethod.TIES, MergeMethod.DARE_TIES):
            base_model_id = (
                Prompt.ask("Base Model Repository ID", default=model_a_id).strip()
                if is_interactive
                else model_a_id
            )
            density = (
                float(Prompt.ask("Weight density [0.0 - 1.0]", default="0.5"))
                if is_interactive
                else 0.5
            )
            weight = (
                float(Prompt.ask("Weight coefficient [0.0 - 1.0]", default="0.5"))
                if is_interactive
                else 0.5
            )
            params = {"density": density, "weight": weight}
        elif method == MergeMethod.LINEAR:
            weight_a = (
                float(Prompt.ask("Weight for Model A", default="0.5")) if is_interactive else 0.5
            )
            weight_b = (
                float(Prompt.ask("Weight for Model B", default="0.5")) if is_interactive else 0.5
            )
            params = {"weight_a": weight_a, "weight_b": weight_b}

    # 4. Hardware and Resource Estimation
    out.print("\n[bold cyan]Step 4: Resource & Hardware Verification[/bold cyan]")
    num_models = 3 if method in (MergeMethod.TIES, MergeMethod.DARE_TIES) else 2
    resource_est = estimate_merge_resources(
        params_per_model=model_a_info.estimated_params,
        num_models=num_models,
        output_dir=Path.cwd() / "merges" / merge_name,
    )
    out.print(render_resource_table(resource_est))

    for warning in resource_est.warnings:
        out.print(f"[yellow]⚠ Warning:[/yellow] {warning}")

    # 5. Generate and show YAML
    out.print("\n[bold cyan]Step 5: Generating mergekit Configuration[/bold cyan]")
    yaml_str = generate_merge_yaml(
        method=method,
        model_a=model_a_id,
        model_b=model_b_id,
        base_model=base_model_id,
        num_layers=model_a_info.num_hidden_layers,
        parameters=params,
    )
    config_file = write_merge_config(merge_name, yaml_str)
    out.print(f"[bold green]Saved configuration to:[/bold green] {config_file}\n")
    out.print(Syntax(yaml_str, "yaml", theme="monokai", line_numbers=True))

    # Always ensure model card is generated
    output_dir = Path.cwd() / "merges" / merge_name
    write_model_card(
        output_dir=output_dir,
        name=merge_name,
        models=[model_a_id, model_b_id],
        method=method.value,
        parameters=params,
        config_yaml=yaml_str,
    )

    # 6. Colab or Local Execution
    if colab:
        colab_file = generate_colab_notebook(merge_name, yaml_str)
        out.print(f"\n[bold green]✓ Google Colab notebook generated:[/bold green] {colab_file}")
        out.print(
            "[dim]Open this notebook in Google Colab (https://colab.research.google.com) "
            "to merge with free T4/A100 GPU acceleration without local RAM limits.[/dim]\n"
        )
        return

    out.print("\n[bold cyan]Step 6: Execution[/bold cyan]")
    if not is_mergekit_installed():
        out.print(
            "[yellow]Note:[/yellow] 'mergekit-yaml' is not found in your PATH.\n"
            "To execute locally, install mergekit dependencies:\n"
            "  [bold cyan]pip install lathe-agent[merge][/bold cyan]\n"
            "Or generate a Google Colab notebook:\n"
            f"  [bold cyan]lathe merge --colab --name {merge_name}[/bold cyan]\n"
        )
        return

    should_run = (
        Confirm.ask("Execute mergekit locally now?", default=True) if is_interactive else True
    )
    if should_run:
        out.print(f"\n[bold green]Executing merge into merges/{merge_name}...[/bold green]")
        run_mergekit(config_file, output_dir=output_dir, out_console=out)
        out.print(f"\n[bold green]✓ Merged model created in merges/{merge_name}![/bold green]\n")
