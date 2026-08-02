"""ApplyPilot CLI — the main entry point."""

from __future__ import annotations

import logging
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

try:
    from applypilot import __version__
except Exception:
    __version__ = "dev"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

app = typer.Typer(
    name="applypilot",
    help="AI-powered end-to-end job application pipeline.",
    no_args_is_help=True,
)
console = Console()
log = logging.getLogger(__name__)

# Valid pipeline stages (in execution order)
VALID_STAGES = ("discover", "enrich", "score", "tailor", "cover", "pdf")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bootstrap() -> None:
    """Common setup: load env, create dirs, init DB."""
    from applypilot.config import load_env, ensure_dirs
    from applypilot.database import init_db

    load_env()
    ensure_dirs()
    init_db()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold]applypilot[/bold] {__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """ApplyPilot — AI-powered end-to-end job application pipeline."""


@app.command()
def init() -> None:
    """Run the first-time setup wizard (profile, resume, search config)."""
    from applypilot.wizard.init import run_wizard

    run_wizard()


@app.command()
def discover(
    preset: str | None = typer.Option(None, "--preset", help="Named filter preset from searches.yaml"),
    hours_old: int | None = typer.Option(None, "--hours-old", help="Restrict to jobs younger than N hours"),
    results_per_site: int | None = typer.Option(None, "--results-per-site", help="Max results per site"),
    remote: bool | None = typer.Option(None, "--remote", help="Force remote-only search"),
    selected: str | None = typer.Option(None, "--selected", help="Comma-separated selected search labels"),
) -> None:
    """Run job discovery with optional filter presets."""
    _bootstrap()

    from applypilot.config import load_search_config
    from applypilot.discovery.jobspy import run_discovery

    cfg = load_search_config() or {}
    overrides: dict = {}
    if hours_old is not None:
        defaults = cfg.setdefault("defaults", {})
        defaults["hours_old"] = hours_old
        overrides["hours_old"] = hours_old
    if results_per_site is not None:
        defaults = cfg.setdefault("defaults", {})
        defaults["results_per_site"] = results_per_site
        overrides["results_per_site"] = results_per_site
    if remote is not None:
        cfg["remote_default"] = remote
        overrides["remote"] = remote
    if selected:
        cfg["selected"] = [s.strip() for s in selected.split(",") if s.strip()]

    result = run_discovery(cfg=cfg, filter_preset=preset, filter_overrides=overrides or None)
    console.print(f"\n[green]Discovery complete:[/green] {result}")


@app.command()
def run(
    stages: list[str] | None = typer.Argument(
        None,
        help=(
            "Pipeline stages to run. "
            f"Valid: {', '.join(VALID_STAGES)}, all. "
            "Defaults to 'all' if omitted."
        ),
    ),
    min_score: int = typer.Option(7, "--min-score", help="Minimum fit score for tailor/cover stages."),
    workers: int = typer.Option(1, "--workers", "-w", help="Parallel threads for discovery/enrichment stages."),
    stream: bool = typer.Option(False, "--stream", help="Run stages concurrently (streaming mode)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview stages without executing."),
    validation: str = typer.Option(
        "normal",
        "--validation",
        help=(
            "Validation strictness for tailor/cover stages. "
            "strict: banned words = errors, judge must pass. "
            "normal: banned words = warnings only (default, recommended for Gemini free tier). "
            "lenient: banned words ignored, LLM judge skipped (fastest, fewest API calls)."
        ),
    ),
) -> None:
    """Run pipeline stages: discover, enrich, score, tailor, cover, pdf."""
    _bootstrap()

    from applypilot.pipeline import run_pipeline

    stage_list = stages if stages else ["all"]

    # Validate stage names
    for s in stage_list:
        if s != "all" and s not in VALID_STAGES:
            console.print(
                f"[red]Unknown stage:[/red] '{s}'. "
                f"Valid stages: {', '.join(VALID_STAGES)}, all"
            )
            raise typer.Exit(code=1)

    # Gate AI stages behind Tier 2
    llm_stages = {"score", "tailor", "cover"}
    if any(s in stage_list for s in llm_stages) or "all" in stage_list:
        from applypilot.config import check_tier
        check_tier(2, "AI scoring/tailoring")

    # Validate the --validation flag value
    valid_modes = ("strict", "normal", "lenient")
    if validation not in valid_modes:
        console.print(
            f"[red]Invalid --validation value:[/red] '{validation}'. "
            f"Choose from: {', '.join(valid_modes)}"
        )
        raise typer.Exit(code=1)

    result = run_pipeline(
        stages=stage_list,
        min_score=min_score,
        dry_run=dry_run,
        stream=stream,
        workers=workers,
        validation_mode=validation,
    )

    if result.get("errors"):
        raise typer.Exit(code=1)


@app.command()
def apply(
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max applications to submit."),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of parallel browser workers."),
    min_score: int = typer.Option(7, "--min-score", help="Minimum fit score for job selection."),
    model: str = typer.Option("deepseek-chat", "--model", "-m", help="Model name (for DeepSeek or Claude)."),
    continuous: bool = typer.Option(False, "--continuous", "-c", help="Run forever, polling for new jobs."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview actions without submitting."),
    headless: bool = typer.Option(False, "--headless", help="Run browsers in headless mode."),
    provider: str = typer.Option("patchright", "--provider", help="Agent provider: 'patchright', 'deepseek', 'claude', or 'browser-use'."),
    url: Optional[str] = typer.Option(None, "--url", help="Apply to a specific job URL."),
    gen: bool = typer.Option(False, "--gen", help="Generate prompt file for manual debugging instead of running."),
    mark_applied: Optional[str] = typer.Option(None, "--mark-applied", help="Manually mark a job URL as applied."),
    mark_failed: Optional[str] = typer.Option(None, "--mark-failed", help="Manually mark a job URL as failed (provide URL)."),
    fail_reason: Optional[str] = typer.Option(None, "--fail-reason", help="Reason for --mark-failed."),
    reset_failed: bool = typer.Option(False, "--reset-failed", help="Reset all failed jobs for retry."),
) -> None:
    """Launch auto-apply to submit job applications."""
    _bootstrap()

    from applypilot.config import check_tier, PROFILE_PATH as _profile_path
    from applypilot.database import get_connection

    # --- Utility modes (no Chrome/Claude needed) ---

    if mark_applied:
        from applypilot.apply.launcher import mark_job
        mark_job(mark_applied, "applied")
        console.print(f"[green]Marked as applied:[/green] {mark_applied}")
        return

    if mark_failed:
        from applypilot.apply.launcher import mark_job
        mark_job(mark_failed, "failed", reason=fail_reason)
        console.print(f"[yellow]Marked as failed:[/yellow] {mark_failed} ({fail_reason or 'manual'})")
        return

    if reset_failed:
        from applypilot.apply.launcher import reset_failed as do_reset
        count = do_reset()
        console.print(f"[green]Reset {count} failed job(s) for retry.[/green]")
        return

    # --- Full apply mode ---

    # Check 1: Tier check (Claude needs Tier 3, DeepSeek needs Tier 2, Patchright needs Tier 2)
    if provider == "claude":
        check_tier(3, "auto-apply (Claude)")
    else:
        check_tier(2, f"auto-apply ({provider})")

    # Check 2: Profile exists
    if not _profile_path.exists():
        console.print(
            "[red]Profile not found.[/red]\n"
            "Run [bold]applypilot init[/bold] to create your profile first."
        )
        raise typer.Exit(code=1)

    # Check 3: Tailored resumes exist (skip for --gen with --url)
    if not (gen and url):
        conn = get_connection()
        ready = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL AND (apply_status IS NULL OR apply_status != 'applied')"
        ).fetchone()[0]
        if ready == 0:
            console.print(
                "[red]No tailored resumes ready.[/red]\n"
                "Run [bold]applypilot run score tailor[/bold] first to prepare applications."
            )
            raise typer.Exit(code=1)

    if gen:
        from applypilot.apply.launcher import gen_prompt, BASE_CDP_PORT
        target = url or ""
        if not target:
            console.print("[red]--gen requires --url to specify which job.[/red]")
            raise typer.Exit(code=1)
        prompt_file = gen_prompt(target, min_score=min_score, model=model)
        if not prompt_file:
            console.print("[red]No matching job found for that URL.[/red]")
            raise typer.Exit(code=1)
        mcp_path = _profile_path.parent / ".mcp-apply-0.json"
        console.print(f"[green]Wrote prompt to:[/green] {prompt_file}")
        console.print(f"\n[bold]Run manually:[/bold]")
        console.print(
            f"  claude --model {model} -p "
            f"--mcp-config {mcp_path} "
            f"--permission-mode bypassPermissions < {prompt_file}"
        )
        return

    from applypilot.apply.launcher import main as apply_main

    effective_limit = limit if limit is not None else (0 if continuous else 1)

    console.print("\n[bold blue]Launching Auto-Apply[/bold blue]")
    console.print(f"  Limit:    {'unlimited' if continuous else effective_limit}")
    console.print(f"  Workers:  {workers}")
    console.print(f"  Model:    {model}")
    console.print(f"  Provider: {provider}")
    console.print(f"  Headless: {headless}")
    console.print(f"  Dry run:  {dry_run}")
    if url:
        console.print(f"  Target:   {url}")
    console.print()

    apply_main(
        limit=effective_limit,
        target_url=url,
        min_score=min_score,
        headless=headless,
        model=model,
        dry_run=dry_run,
        continuous=continuous,
        workers=workers,
        provider=provider,
    )


@app.command()
def status() -> None:
    """Show pipeline statistics from the database."""
    _bootstrap()

    from applypilot.database import get_stats

    stats = get_stats()

    console.print("\n[bold]ApplyPilot Pipeline Status[/bold]\n")

    # Summary table
    summary = Table(title="Pipeline Overview", show_header=True, header_style="bold cyan")
    summary.add_column("Metric", style="bold")
    summary.add_column("Count", justify="right")

    summary.add_row("Total jobs discovered", str(stats["total"]))
    summary.add_row("With full description", str(stats["with_description"]))
    summary.add_row("Pending enrichment", str(stats["pending_detail"]))
    summary.add_row("Enrichment errors", str(stats["detail_errors"]))
    summary.add_row("Scored by LLM", str(stats["scored"]))
    summary.add_row("Pending scoring", str(stats["unscored"]))
    summary.add_row("Tailored resumes", str(stats["tailored"]))
    summary.add_row("Pending tailoring (7+)", str(stats["untailored_eligible"]))
    summary.add_row("Cover letters", str(stats["with_cover_letter"]))
    summary.add_row("Ready to apply", str(stats["ready_to_apply"]))
    summary.add_row("Applied", str(stats["applied"]))
    summary.add_row("Apply errors", str(stats["apply_errors"]))

    console.print(summary)

    # Score distribution
    if stats["score_distribution"]:
        dist_table = Table(title="\nScore Distribution", show_header=True, header_style="bold yellow")
        dist_table.add_column("Score", justify="center")
        dist_table.add_column("Count", justify="right")
        dist_table.add_column("Bar")

        max_count = max(count for _, count in stats["score_distribution"]) or 1
        for score, count in stats["score_distribution"]:
            bar_len = int(count / max_count * 30)
            if score >= 7:
                color = "green"
            elif score >= 5:
                color = "yellow"
            else:
                color = "red"
            bar = f"[{color}]{'=' * bar_len}[/{color}]"
            dist_table.add_row(str(score), str(count), bar)

        console.print(dist_table)

    # By site
    if stats["by_site"]:
        site_table = Table(title="\nJobs by Source", show_header=True, header_style="bold magenta")
        site_table.add_column("Site")
        site_table.add_column("Count", justify="right")

        for site, count in stats["by_site"]:
            site_table.add_row(site or "Unknown", str(count))

        console.print(site_table)

    console.print()


@app.command()
def dashboard() -> None:
    """Generate and open the HTML dashboard in your browser."""
    _bootstrap()

    from applypilot.view import open_dashboard

    open_dashboard()


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
    port: int = typer.Option(5000, "--port", "-p", help="Bind port."),
    debug: bool = typer.Option(False, "--debug", "-d", help="Run in debug mode."),
) -> None:
    """Start the Flask web dashboard server."""
    _bootstrap()

    from applypilot.web import create_app

    app = create_app()
    console.print(f"[green]Web dashboard starting on http://{host}:{port}[/green]")
    app.run(host=host, port=port, debug=debug)


@app.command()
def doctor() -> None:
    """Check your setup and diagnose missing requirements."""
    import shutil
    from applypilot.config import (
        load_env, PROFILE_PATH, RESUME_PATH, RESUME_PDF_PATH,
        SEARCH_CONFIG_PATH, ENV_PATH, get_chrome_path,
    )

    load_env()

    ok_mark = "[green]OK[/green]"
    fail_mark = "[red]MISSING[/red]"
    warn_mark = "[yellow]WARN[/yellow]"

    results: list[tuple[str, str, str]] = []  # (check, status, note)

    # --- Tier 1 checks ---
    # Profile
    if PROFILE_PATH.exists():
        results.append(("profile.json", ok_mark, str(PROFILE_PATH)))
    else:
        results.append(("profile.json", fail_mark, "Run 'applypilot init' to create"))

    # Resume
    if RESUME_PATH.exists():
        results.append(("resume.txt", ok_mark, str(RESUME_PATH)))
    elif RESUME_PDF_PATH.exists():
        results.append(("resume.txt", warn_mark, "Only PDF found — plain-text needed for AI stages"))
    else:
        results.append(("resume.txt", fail_mark, "Run 'applypilot init' to add your resume"))

    # Search config
    if SEARCH_CONFIG_PATH.exists():
        results.append(("searches.yaml", ok_mark, str(SEARCH_CONFIG_PATH)))
    else:
        results.append(("searches.yaml", warn_mark, "Will use example config — run 'applypilot init'"))

    # jobspy (discovery dep installed separately)
    try:
        import jobspy  # noqa: F401
        results.append(("python-jobspy", ok_mark, "Job board scraping available"))
    except ImportError:
        results.append(("python-jobspy", warn_mark,
                        "pip install --no-deps python-jobspy && pip install pydantic tls-client requests markdownify regex"))

    # --- Tier 2 checks ---
    import os
    has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_deepseek = bool(os.environ.get("DEEPSEEK_API_KEY"))
    has_local = bool(os.environ.get("LLM_URL"))
    if has_gemini:
        model = os.environ.get("LLM_MODEL", "gemini-2.0-flash")
        results.append(("LLM API key", ok_mark, f"Gemini ({model})"))
    elif has_openai:
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        results.append(("LLM API key", ok_mark, f"OpenAI ({model})"))
    elif has_deepseek:
        model = os.environ.get("LLM_MODEL", "deepseek-chat")
        results.append(("LLM API key", ok_mark, f"DeepSeek ({model})"))
    elif has_local:
        results.append(("LLM API key", ok_mark, f"Local: {os.environ.get('LLM_URL')}"))
    else:
        results.append(("LLM API key", fail_mark,
                        "Set GEMINI_API_KEY, OPENAI_API_KEY, or DEEPSEEK_API_KEY in ~/.applypilot/.env (run 'applypilot init')"))

    # --- Tier 3 checks ---
    # Claude Code CLI
    claude_bin = shutil.which("claude")
    if claude_bin:
        results.append(("Claude Code CLI", ok_mark, claude_bin))
    else:
        results.append(("Claude Code CLI", fail_mark,
                        "Install from https://claude.ai/code (needed for auto-apply)"))

    # Chrome
    try:
        chrome_path = get_chrome_path()
        results.append(("Chrome/Chromium", ok_mark, chrome_path))
    except FileNotFoundError:
        results.append(("Chrome/Chromium", fail_mark,
                        "Install Chrome or set CHROME_PATH env var (needed for auto-apply)"))

    # Node.js / npx (for Playwright MCP)
    npx_bin = shutil.which("npx")
    if npx_bin:
        results.append(("Node.js (npx)", ok_mark, npx_bin))
    else:
        results.append(("Node.js (npx)", fail_mark,
                        "Install Node.js 18+ from nodejs.org (needed for auto-apply)"))

    # CapSolver (optional)
    capsolver = os.environ.get("CAPSOLVER_API_KEY")
    if capsolver:
        results.append(("CapSolver API key", ok_mark, "CAPTCHA solving enabled"))
    else:
        results.append(("CapSolver API key", "[dim]optional[/dim]",
                        "Set CAPSOLVER_API_KEY in .env for CAPTCHA solving"))

    # --- Render results ---
    console.print()
    console.print("[bold]ApplyPilot Doctor[/bold]\n")

    col_w = max(len(r[0]) for r in results) + 2
    for check, status, note in results:
        pad = " " * (col_w - len(check))
        console.print(f"  {check}{pad}{status}  [dim]{note}[/dim]")

    console.print()

    # Tier summary
    from applypilot.config import get_tier, TIER_LABELS
    tier = get_tier()
    console.print(f"[bold]Current tier: Tier {tier} — {TIER_LABELS[tier]}[/bold]")

    if tier == 1:
        console.print("[dim]  -> Tier 2 unlocks: scoring, tailoring, cover letters (needs LLM API key)[/dim]")
        console.print("[dim]  -> Tier 3 unlocks: auto-apply (needs Claude Code CLI + Chrome + Node.js)[/dim]")
    elif tier == 2:
        console.print("[dim]  -> Tier 3 unlocks: auto-apply (needs Claude Code CLI + Chrome + Node.js)[/dim]")

    console.print()


# ---------------------------------------------------------------------------
# Knowledge base management
# ---------------------------------------------------------------------------

@app.command()
def knowledge(
    query: Optional[str] = typer.Argument(None, help="Search term to filter knowledge entries."),
    limit: int = typer.Option(20, "--limit", "-n", help="Max entries to show."),
    delete: Optional[int] = typer.Option(None, "--delete", help="Delete a knowledge entry by ID."),
) -> None:
    """View and manage the knowledge base."""
    _bootstrap()
    from applypilot.knowledge import get_all_knowledge, search_knowledge, delete_knowledge

    if delete is not None:
        ok = delete_knowledge(delete)
        if ok:
            console.print(f"[green]Deleted knowledge entry #{delete}[/green]")
        else:
            console.print(f"[red]Entry #{delete} not found.[/red]")
        return

    if query:
        entries = search_knowledge(query, limit=limit)
    else:
        entries = get_all_knowledge(limit=limit)

    if not entries:
        console.print("[yellow]No knowledge entries found.[/yellow]")
        return

    table = Table(title=f"Knowledge Base ({len(entries)} entries)")
    table.add_column("ID", style="dim", width=4)
    table.add_column("Question", width=40)
    table.add_column("Answer", width=40)
    table.add_column("Conf", width=5)
    table.add_column("Source", width=10)
    table.add_column("Used", width=5)

    for e in entries:
        table.add_row(
            str(e["id"]),
            e["question"][:38],
            e["answer"][:38],
            str(e.get("confidence", "")),
            str(e.get("source", "")),
            str(e.get("used_count", 0)),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Alerts management
# ---------------------------------------------------------------------------

@app.command()
def alerts() -> None:
    """List pending alerts waiting for user response."""
    _bootstrap()
    from applypilot.alerts import get_pending_alerts

    pending = get_pending_alerts() or []
    if not pending:
        console.print("[green]No pending alerts.[/green]")
        return

    table = Table(title=f"Pending Alerts ({len(pending)})")
    table.add_column("ID", width=4)
    table.add_column("Question", width=50)
    table.add_column("Status", width=10)
    table.add_column("Job", width=30)
    for a in pending:
        table.add_row(
            str(a["id"]),
            (a.get("question") or a.get("field_label", ""))[:48],
            a.get("status", ""),
            (a.get("job_title", "") or "")[:28],
        )
    console.print(table)


@app.command()
def answer(
    alert_id: int = typer.Argument(..., help="Alert ID to answer."),
    answer_text: str = typer.Argument(..., help="Your answer text."),
) -> None:
    """Answer a pending alert from the CLI."""
    _bootstrap()
    from applypilot.alerts import answer_alert as _answer_alert
    from applypilot.apply.apply_agent import signal_alert_answered

    ok = _answer_alert(alert_id, answer_text)
    if ok:
        signal_alert_answered(alert_id)
        console.print(f"[green]Alert #{alert_id} answered: '{answer_text[:60]}'[/green]")
    else:
        console.print(f"[red]Alert #{alert_id} not found or already answered.[/red]")


# ---------------------------------------------------------------------------
# Telegram listener (polling mode)
# ---------------------------------------------------------------------------

@app.command()
def telegram(
    poll: bool = typer.Option(False, "--poll", "-p", help="Start polling for Telegram updates."),
) -> None:
    """Interact with Telegram bot — poll for /answer commands."""
    _bootstrap()
    if not poll:
        console.print("[yellow]Use --poll to start polling for Telegram updates.[/yellow]")
        return

    from applypilot.alerts import get_pending_alerts, send_telegram_message
    import requests

    config.load_env()
    import os

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        console.print("[red]TELEGRAM_BOT_TOKEN not set in .env[/red]")
        raise typer.Exit(1)

    offset = 0
    console.print("[green]Polling Telegram for /answer commands... (Ctrl+C to stop)[/green]")

    try:
        while True:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            resp = requests.get(url, params={
                "offset": offset,
                "timeout": 30,
            }, timeout=35)
            data = resp.json()
            if not data.get("ok"):
                time.sleep(5)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {}) or update.get("edited_message", {})
                text = (msg.get("text") or "").strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if not text or not chat_id:
                    continue
                if text.startswith("/answer"):
                    parts = text.split(maxsplit=2)
                    if len(parts) >= 3:
                        try:
                            aid = int(parts[1])
                            ans = parts[2]
                            from applypilot.alerts import answer_alert
                            if answer_alert(aid, ans):
                                signal_alert_answered(aid)
                                send_telegram_message(
                                    f"✅ Resposta salva para alerta #{aid}.",
                                    chat_id=chat_id,
                                )
                                console.print(f"[green]Alert #{aid} answered via Telegram: '{ans[:50]}'[/green]")
                            else:
                                send_telegram_message(
                                    f"Alerta #{aid} nao encontrado.",
                                    chat_id=chat_id,
                                )
                        except (ValueError, IndexError):
                            send_telegram_message(
                                "Formato: /answer <id> <texto>",
                                chat_id=chat_id,
                            )
                elif text == "/status":
                    pending = get_pending_alerts()
                    if pending:
                        msg_lines = [f"Alertas pendentes ({len(pending)}):"]
                        for a in pending[:5]:
                            msg_lines.append(f"  #{a['id']}: {a.get('question','')[:60]}")
                        send_telegram_message("\n".join(msg_lines), chat_id=chat_id)
                    else:
                        send_telegram_message("Nenhum alerta pendente.", chat_id=chat_id)
                elif text == "/help":
                    send_telegram_message(
                        "Comandos:\n"
                        "/answer <id> <texto> - Responder alerta\n"
                        "/status - Ver alertas pendentes\n"
                        "/help - Esta mensagem",
                        chat_id=chat_id,
                    )
            time.sleep(0.5)
    except KeyboardInterrupt:
        console.print("\n[yellow]Telegram polling stopped.[/yellow]")


@app.command()
def daily_report(
    hours: int = typer.Option(24, "--hours", "-h", help="Hours back to search (default: 24 = yesterday)."),
    top: int = typer.Option(15, "--top", "-t", help="Max jobs to include in Telegram message."),
    no_telegram: bool = typer.Option(False, "--no-telegram", help="Skip Telegram send, only save local report."),
) -> None:
    """Discover + score jobs from the last N hours and send a Telegram report."""
    from datetime import datetime, timedelta
    import os

    _bootstrap()

    from applypilot.config import load_search_config, APP_DIR
    cfg = load_search_config() or {}
    cfg.setdefault("defaults", {})["hours_old"] = hours

    from applypilot.discovery.jobspy import run_discovery
    from applypilot.scoring.scorer import run_scoring
    from applypilot.database import get_connection
    from applypilot.alerts import send_telegram_message

    # Quick LLM health check: fail fast if the API key is out of quota.
    from applypilot.llm import get_client
    try:
        client = get_client()
        test_resp = client.chat([
            {"role": "system", "content": "You are a brief assistant."},
            {"role": "user", "content": "Say 'ok' and nothing else."},
        ], max_tokens=10, temperature=0.0)
        console.print(f"[dim]LLM health check: OK ({len(test_resp)} chars)[/dim]")
    except Exception as e:
        err_msg = str(e)
        console.print(f"\n[red]LLM API error: {err_msg[:200]}[/red]")
        console.print("[yellow]Check your API key, quota/billing, and LLM_MODEL in GitHub secrets.[/yellow]")
        if not no_telegram:
            send_telegram_message(
                f"<b>ApplyPilot - Relatorio Diario</b>\n"
                f"{datetime.now().strftime('%d/%m/%Y')}\n\n"
                f"ERRO: API do LLM retornou erro:\n"
                f"{err_msg[:200]}\n\n"
                f"Verifique sua chave, quota e billing no Google Cloud Console.",
            )
        raise SystemExit(1)

    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

    console.print(f"\n[bold blue]Daily Report[/bold blue] — buscando vagas das ultimas {hours}h")
    console.print()

    console.print("[cyan]Stage 1/2: Discovery...[/cyan]")
    result = run_discovery(cfg=cfg)
    console.print(f"  New: {result['new']} | Dupes: {result['existing']} | Errors: {result['errors']}")

    console.print("\n[cyan]Stage 2/2: Scoring pending jobs...[/cyan]")
    score_result = run_scoring()
    console.print(
        f"  Scored: {score_result['scored']} | Errors: {score_result['errors']} | "
        f"Time: {score_result['elapsed']:.0f}s"
    )
    console.print(
        f"  Detalhe: {score_result.get('llm_calls', score_result['scored'])} chamadas LLM, "
        f"{score_result.get('auto_skipped', 0)} puladas automaticamente pelo titulo"
    )

    c = get_connection()
    rows = c.execute("""
        SELECT fit_score, title, site, location, url, full_description
        FROM jobs
        WHERE fit_score >= 6 AND discovered_at >= ?
        ORDER BY fit_score DESC, title
    """, (cutoff,)).fetchall()

    total_with_score = len(rows)

    if total_with_score == 0:
        console.print("\n[yellow]Nenhuma vaga com score >= 6 encontrada neste periodo.[/yellow]")
        if not no_telegram:
            send_telegram_message(
                f"<b>ApplyPilot - Relatorio Diario</b>\n"
                f"{datetime.now().strftime('%d/%m/%Y')}\n\n"
                f"Nenhuma vaga com score >= 6 nas ultimas {hours}h.\n"
                f"Vagas novas: {result['new']} | Pontuadas: {score_result['scored']} | "
                f"Erros: {score_result['errors']} | LLM calls: {score_result.get('llm_calls', score_result['scored'])}",
            )
        return

    top_rows = rows[:top]
    date_str = datetime.now().strftime("%d/%m/%Y")

    tg_lines = [
        f"<b>ApplyPilot - Relatorio Diario</b>",
        f"<b>{date_str}</b>",
        f"",
        f"Vagas com score >= 6 encontradas: <b>{total_with_score}</b>",
        f"(Mostrando as {len(top_rows)} melhores)",
        f"",
    ]

    for r in top_rows:
        score_emoji = "🟢" if r["fit_score"] >= 9 else "🔵" if r["fit_score"] >= 8 else "🟡"
        loc = (r["location"] or "Nao informada")[:40]
        desc = (r["full_description"] or "")[:120].replace("\n", " ").strip()
        title = r["title"][:60]
        tg_lines.append(
            f"{score_emoji} <b>[{r['fit_score']}/10]</b> {title}\n"
            f"   {loc}\n"
            f"   {desc}...\n"
            f"   <a href='{r['url']}'>Ver vaga</a>\n"
        )

    if total_with_score > top:
        tg_lines.append(f"... e mais {total_with_score - top} vaga(s).")

    tg_lines.append(
        f"\nNovas: {result['new']} | Pontuadas: {score_result['scored']} | "
        f"Erros: {score_result['errors']} | LLM calls: {score_result.get('llm_calls', score_result['scored'])} | "
        f"Total DB: {c.execute('SELECT count(*) FROM jobs').fetchone()[0]}"
    )

    tg_message = "\n".join(tg_lines)

    report_path = APP_DIR / "daily_report.md"
    md_lines = [
        f"# ApplyPilot - Relatorio Diario - {date_str}",
        "",
        f"Vagas com score >= 6: **{total_with_score}**",
        f"Vagas novas descobertas: {result['new']}",
        f"Vagas pontuadas: {score_result['scored']}",
        f"Periodo: ultimas {hours}h",
        "",
    ]
    for r in rows:
        desc = (r["full_description"] or "")[:250].replace("\n", " ").strip()
        md_lines.append(f"## [{r['fit_score']}/10] {r['title']}")
        md_lines.append(f"- Local: {r['location'] or 'Nao informada'}")
        md_lines.append(f"- Link: {r['url']}")
        md_lines.append(f"- Descricao: {desc}...")
        md_lines.append("")
    report_path.write_text("\n".join(md_lines), encoding="utf-8")

    if not no_telegram:
        ok = send_telegram_message(tg_message)
        if ok:
            console.print(f"\n[green]Telegram enviado com {len(top_rows)} vagas.[/green]")
        else:
            console.print(f"\n[yellow]Falha ao enviar Telegram. Verifique TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env[/yellow]")
    else:
        console.print(f"\n[dim]Telegram skipado (--no-telegram).[/dim]")

    console.print(f"[dim]Relatorio local salvo: {report_path}[/dim]")
    console.print(f"[bold]Vagas score >= 6 encontradas: {total_with_score}[/bold]\n")


if __name__ == "__main__":
    app()
