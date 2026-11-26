"""Command line: seed, review, eval."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .evaluate import EvalResult, run_eval
from .model import FakeReviewer, FaultPlan, ModelError, OpenAICompatModel, ReviewModel
from .pipeline import review_text
from .playbook import ISSUE_ORDER, Playbook, load_playbook
from .report import render_review
from .seed import write_dataset

app = typer.Typer(add_completion=False, help="Anchor every contract finding to verbatim text.")
console = Console()


def _model(kind: str, fault_plan: Path | None) -> ReviewModel:
    if kind == "fake":
        return FakeReviewer(FaultPlan.load(fault_plan) if fault_plan else None)
    if kind == "openai":
        try:
            return OpenAICompatModel.from_env()
        except ModelError as exc:
            raise typer.BadParameter(str(exc)) from exc
    raise typer.BadParameter("model must be 'fake' or 'openai'")


@app.command()
def seed(
    out: Annotated[Path, typer.Option(help="Output directory")] = Path("data"),
    seed: Annotated[int, typer.Option(help="Random seed")] = 7,
) -> None:
    """Generate 120 synthetic contracts with gold labels, a playbook and a fault plan."""
    counts = write_dataset(out, seed)
    console.print(f"Wrote {counts['contracts']} contracts and {counts['labels']} labels to {out}/")


@app.command()
def review(
    contract: Annotated[Path, typer.Argument(help="Plain-text contract")],
    playbook: Annotated[Path | None, typer.Option(help="Playbook YAML")] = None,
    model: Annotated[str, typer.Option(help="fake or openai")] = "fake",
    fault_plan: Annotated[Path | None, typer.Option(help="Faults for the fake model")] = None,
    out: Annotated[Path | None, typer.Option(help="Write the report here")] = None,
) -> None:
    """Review one contract against the playbook and print a Markdown report."""
    book = load_playbook(playbook)
    result = review_text(
        contract.read_text("utf-8"), contract.stem, book, _model(model, fault_plan)
    )
    report = render_review(result, book)
    if out:
        out.write_text(report, "utf-8")
        console.print(f"Wrote {out}")
    else:
        typer.echo(report)


def _table(result: EvalResult, book: Playbook) -> Table:
    table = Table(title="RED recall and precision per issue (anchored vs trust-model)")
    for name, justify in (
        ("Issue", "left"),
        ("Gold RED", "right"),
        ("Recall", "right"),
        ("Precision", "right"),
        ("Trust recall", "right"),
        ("Trust precision", "right"),
        ("Anchor rate", "right"),
        ("Value acc.", "right"),
    ):
        table.add_column(name, justify=justify)  # type: ignore[arg-type]
    rows = [(book.issues[n].title, result.issues[n]) for n in ISSUE_ORDER]
    rows.append(("All issues", result.total))
    for label, c in rows:
        table.add_row(
            label,
            str(c.gold_red),
            f"{result.red_recall(c):.3f}",
            f"{result.red_precision(c):.3f}",
            f"{result.baseline_recall(c):.3f}",
            f"{result.baseline_precision(c):.3f}",
            f"{c.anchored / c.present:.3f}",
            f"{c.value_ok / c.present:.3f}",
        )
    return table


@app.command("eval")
def evaluate_command(
    data: Annotated[Path, typer.Option(help="Directory written by `seed`")] = Path("data"),
    out: Annotated[Path | None, typer.Option(help="Write eval.md and eval.json here")] = None,
) -> None:
    """Score the pipeline and the trust-model baseline against the gold labels."""
    result, _, book = run_eval(data)
    console.print(_table(result, book))
    for kind, counts in result.faults.items():
        console.print(f"{kind}: caught {counts['caught']} of {counts['injected']}")
    console.print(
        f"offset slice failures: {result.bad_offsets}; unexplained flags: {result.false_flags}; "
        f"needs review: {result.total.needs_review}"
    )
    if out:
        out.mkdir(parents=True, exist_ok=True)
        (out / "eval.md").write_text(result.to_markdown(book), "utf-8")
        (out / "eval.json").write_text(result.model_dump_json(indent=1) + "\n", "utf-8")
        console.print(f"Wrote {out}/eval.md and {out}/eval.json")


if __name__ == "__main__":
    app()
