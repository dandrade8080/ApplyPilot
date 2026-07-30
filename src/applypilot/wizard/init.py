"""ApplyPilot first-time setup wizard.

Interactive flow that creates ~/.applypilot/ with:
  - resume.txt (and optionally resume.pdf)
  - profile.json
  - searches.yaml
  - .env (LLM API key)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from applypilot.config import (
    APP_DIR,
    ENV_PATH,
    PROFILE_PATH,
    RESUME_PATH,
    RESUME_PDF_PATH,
    SEARCH_CONFIG_PATH,
    ensure_dirs,
)

console = Console()


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

def _setup_resume() -> None:
    """Prompt for resume file and copy into APP_DIR."""
    console.print(Panel("[bold]Step 1: Resume[/bold]\nPoint to your master resume file (.txt or .pdf)."))

    while True:
        path_str = Prompt.ask("Resume file path")
        src = Path(path_str.strip().strip('"').strip("'")).expanduser().resolve()

        if not src.exists():
            console.print(f"[red]File not found:[/red] {src}")
            continue

        suffix = src.suffix.lower()
        if suffix not in (".txt", ".pdf"):
            console.print("[red]Unsupported format.[/red] Provide a .txt or .pdf file.")
            continue

        if suffix == ".txt":
            shutil.copy2(src, RESUME_PATH)
            console.print(f"[green]Copied to {RESUME_PATH}[/green]")
        elif suffix == ".pdf":
            shutil.copy2(src, RESUME_PDF_PATH)
            console.print(f"[green]Copied to {RESUME_PDF_PATH}[/green]")

            # Also ask for a plain-text version for LLM consumption
            txt_path_str = Prompt.ask(
                "Plain-text version of your resume (.txt)",
                default="",
            )
            if txt_path_str.strip():
                txt_src = Path(txt_path_str.strip().strip('"').strip("'")).expanduser().resolve()
                if txt_src.exists():
                    shutil.copy2(txt_src, RESUME_PATH)
                    console.print(f"[green]Copied to {RESUME_PATH}[/green]")
                else:
                    console.print("[yellow]File not found, skipping plain-text copy.[/yellow]")
        break


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def _setup_profile() -> dict:
    """Walk through profile questions and return a nested profile dict."""
    console.print(Panel("[bold]Step 2: Profile[/bold]\nTell ApplyPilot about yourself. This powers scoring, tailoring, and auto-fill."))

    profile: dict = {}

    # -- Personal --
    console.print("\n[bold cyan]Personal Information[/bold cyan]")
    full_name = Prompt.ask("Full name")
    profile["personal"] = {
        "full_name": full_name,
        "preferred_name": Prompt.ask("Preferred/nickname (leave blank to use first name)", default=""),
        "email": Prompt.ask("Email address"),
        "phone": Prompt.ask("Phone number", default=""),
        "city": Prompt.ask("City"),
        "province_state": Prompt.ask("Province/State (e.g. Ontario, California)", default=""),
        "country": Prompt.ask("Country"),
        "postal_code": Prompt.ask("Postal/ZIP code", default=""),
        "address": Prompt.ask("Street address (optional, used for form auto-fill)", default=""),
        "linkedin_url": Prompt.ask("LinkedIn URL", default=""),
        "github_url": Prompt.ask("GitHub URL (optional)", default=""),
        "portfolio_url": Prompt.ask("Portfolio URL (optional)", default=""),
        "website_url": Prompt.ask("Personal website URL (optional)", default=""),
        "password": Prompt.ask("Job site password (used for login walls during auto-apply)", password=True, default=""),
        "industry": Prompt.ask("Industry (e.g. Marketing, Technology, Finance, Healthcare)", default=""),
    }

    # -- Work Authorization --
    console.print("\n[bold cyan]Work Authorization[/bold cyan]")
    profile["work_authorization"] = {
        "legally_authorized_to_work": Confirm.ask("Are you legally authorized to work in your target country?"),
        "require_sponsorship": Confirm.ask("Will you now or in the future need sponsorship?"),
        "work_permit_type": Prompt.ask("Work permit type (e.g. Citizen, PR, Open Work Permit — leave blank if N/A)", default=""),
    }

    # -- Compensation --
    console.print("\n[bold cyan]Compensation[/bold cyan]")
    salary = Prompt.ask("Expected annual salary (number)", default="")
    salary_currency = Prompt.ask("Currency", default="USD")
    salary_range = Prompt.ask("Acceptable range (e.g. 80000-120000)", default="")
    range_parts = salary_range.split("-") if "-" in salary_range else [salary, salary]
    profile["compensation"] = {
        "salary_expectation": salary,
        "salary_currency": salary_currency,
        "salary_range_min": range_parts[0].strip(),
        "salary_range_max": range_parts[1].strip() if len(range_parts) > 1 else range_parts[0].strip(),
    }

    # -- Experience --
    console.print("\n[bold cyan]Experience[/bold cyan]")
    current_title = Prompt.ask("Current/most recent job title", default="")
    target_role = Prompt.ask("Target role (what you're applying for, e.g. 'Senior Backend Engineer')", default=current_title)
    profile["experience"] = {
        "years_of_experience_total": Prompt.ask("Years of professional experience", default=""),
        "education_level": Prompt.ask("Highest education (e.g. Bachelor's, Master's, PhD, Self-taught)", default=""),
        "current_title": current_title,
        "target_role": target_role,
    }

    # -- Skills Boundary (profession-agnostic) --
    console.print("\n[bold cyan]Skills & Expertise[/bold cyan]")
    console.print("[dim]List your core professional skills. What are you known for?[/dim]")
    console.print("[dim]Examples by profession:[/dim]")
    console.print("[dim]  Marketing: Brand Strategy, Digital Marketing, Campaign Management, SEO, Team Leadership[/dim]")
    console.print("[dim]  Supply Chain: Logistics, Procurement, SAP, Inventory Management, Vendor Negotiation[/dim]")
    console.print("[dim]  Software Engineer: Python, React, AWS, Docker, System Design, PostgreSQL[/dim]")
    console.print("[dim]  Healthcare: Patient Care, Diagnosis, Surgery, EHR Systems, Clinical Research[/dim]")

    primary_skills_raw = Prompt.ask("Your core skills (comma-separated)")
    primary_skills = [s.strip() for s in primary_skills_raw.split(",") if s.strip()]

    tools_raw = Prompt.ask("Tools, platforms & languages you use (comma-separated)", default="")
    tools = [s.strip() for s in tools_raw.split(",") if s.strip()]

    certs_raw = Prompt.ask("Certifications & licenses (comma-separated)", default="")
    certs = [s.strip() for s in certs_raw.split(",") if s.strip()]

    soft_raw = Prompt.ask("Soft skills / leadership competencies (comma-separated)", default="")
    soft = [s.strip() for s in soft_raw.split(",") if s.strip()]

    profile["skills_boundary"] = {
        "primary_skills": primary_skills,
        "tools": tools,
        "certifications": certs,
        "soft_skills": soft,
    }

    # -- Resume Facts (preserved truths for tailoring) --
    console.print("\n[bold cyan]Resume Facts[/bold cyan]")
    console.print("[dim]These are preserved exactly during resume tailoring — the AI will never change them.[/dim]")
    companies = Prompt.ask("Companies to always keep (comma-separated)", default="")
    projects = Prompt.ask("Projects to always keep (comma-separated)", default="")
    school = Prompt.ask("School name(s) to preserve", default="")
    metrics = Prompt.ask("Real metrics to preserve (e.g. '99.9% uptime, 50k users')", default="")
    profile["resume_facts"] = {
        "preserved_companies": [s.strip() for s in companies.split(",") if s.strip()],
        "preserved_projects": [s.strip() for s in projects.split(",") if s.strip()],
        "preserved_school": school.strip(),
        "real_metrics": [s.strip() for s in metrics.split(",") if s.strip()],
    }

    # -- EEO Voluntary (defaults) --
    profile["eeo_voluntary"] = {
        "gender": "Decline to self-identify",
        "race_ethnicity": "Decline to self-identify",
        "veteran_status": "Decline to self-identify",
        "disability_status": "Decline to self-identify",
    }

    # -- Availability --
    profile["availability"] = {
        "earliest_start_date": Prompt.ask("Earliest start date", default="Immediately"),
    }

    # Save
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"\n[green]Profile saved to {PROFILE_PATH}[/green]")
    return profile


# ---------------------------------------------------------------------------
# Search config
# ---------------------------------------------------------------------------

def _setup_searches() -> None:
    """Generate a comprehensive searches.yaml from user input."""
    console.print(Panel("[bold]Step 3: Job Search Config[/bold]\nDefine what jobs you're looking for and where."))

    location = Prompt.ask("Target location (e.g. 'Remote', 'São Paulo', 'New York, NY')", default="Remote")
    distance_str = Prompt.ask("Search radius in miles (0 for remote-only)", default="0")
    try:
        distance = int(distance_str)
    except ValueError:
        distance = 0

    roles_raw = Prompt.ask(
        "Target job titles (comma-separated, e.g. 'Marketing Director, Head of Marketing, CMO')"
    )
    roles = [r.strip() for r in roles_raw.split(",") if r.strip()]

    if not roles:
        console.print("[yellow]No roles provided. Using a default set.[/yellow]")
        roles = ["Manager"]

    console.print("\n[dim]Which job boards to search?[/dim]")
    use_linkedin = Confirm.ask("Search LinkedIn?", default=True)
    use_indeed = Confirm.ask("Search Indeed?", default=True)
    use_glassdoor = Confirm.ask("Search Glassdoor?", default=False)
    use_zip = Confirm.ask("Search ZipRecruiter?", default=False)

    sites = []
    if use_linkedin:
        sites.append("linkedin")
    if use_indeed:
        sites.append("indeed")
    if use_glassdoor:
        sites.append("glassdoor")
    if use_zip:
        sites.append("zip_recruiter")
    if not sites:
        sites = ["linkedin", "indeed"]

    console.print("\n[dim]How far back should we look for jobs?[/dim]")
    hours_old = Prompt.ask("Hours old (e.g. 72 for 3 days, 168 for 1 week)", default="72")
    results_per_site = Prompt.ask("Max results per job board per search", default="50")

    console.print("\n[dim]Are there job title keywords you want to EXCLUDE?[/dim]")
    console.print("[dim]These filter out roles below your target level (e.g. intern, junior, assistant).[/dim]")
    exclude_raw = Prompt.ask(
        "Exclude titles containing (comma-separated)",
        default="intern, internship, estagio, estagiario, trainee, junior, assistant, assistente, auxiliar, apprentice"
    )
    exclude_titles = [e.strip() for e in exclude_raw.split(",") if e.strip()]

    console.print("\n[dim]Country configuration for job boards:[/dim]")
    country_indeed = Prompt.ask("Indeed country code", default="brazil")
    country_code = Prompt.ask("Country code (e.g. BRA, USA, CAN)", default="BRA")

    lines = [
        "# ApplyPilot search configuration",
        "# Generated by: applypilot init",
        "",
        f"country: \"{country_code}\"",
        "",
        "defaults:",
        f"  results_per_site: {results_per_site}",
        f"  hours_old: {hours_old}",
        f"  country_indeed: \"{country_indeed}\"",
        "",
        "locations:",
        f"  - location: \"{location}\"",
        f"    remote: {str(distance == 0).lower()}",
        "",
        "sites:",
    ]
    for s in sites:
        lines.append(f"  - {s}")

    lines.append("")
    lines.append("location_accept:")
    lines.append(f'  - "{location}"')

    if exclude_titles:
        lines.append("")
        lines.append("exclude_titles:")
        for et in exclude_titles:
            lines.append(f'  - "{et}"')

    lines.append("")
    lines.append("queries:")
    for i, role in enumerate(roles):
        lines.append(f'  - query: "{role}"')
        lines.append(f"    tier: {min(i + 1, 3)}")

    SEARCH_CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    console.print(f"[green]Search config saved to {SEARCH_CONFIG_PATH}[/green]")


# ---------------------------------------------------------------------------
# Scoring preferences (NEW — profession-aware)
# ---------------------------------------------------------------------------

_PROFESSION_CATEGORIES = {
    "technology": "Technology & Software",
    "business": "Business & Management (Marketing, Finance, HR, Operations)",
    "supply_chain": "Supply Chain & Logistics",
    "healthcare": "Healthcare & Medical",
    "creative": "Creative & Design",
    "education": "Education & Teaching",
    "legal": "Legal & Compliance",
    "other": "Other / Not listed",
}

_SENIORITY_LEVELS = {
    "executive": "C-level / VP / Executive",
    "director_vp": "Director / VP / Head",
    "senior_manager": "Senior Manager / Manager",
    "senior": "Senior-level individual contributor",
    "mid": "Mid-level",
    "entry": "Entry-level / Recent graduate",
}


def _setup_scoring_preferences() -> None:
    """Configure how jobs are scored — tailored to the user's profession."""
    console.print(Panel(
        "[bold]Step 4: Scoring Preferences[/bold]\n"
        "Tell ApplyPilot about your profession so it scores jobs correctly.\n"
        "A marketing professional and a software engineer need different criteria."
    ))

    console.print("\n[bold cyan]Profession Category[/bold cyan]")
    cat_options = list(_PROFESSION_CATEGORIES.keys())
    cat = Prompt.ask(
        "What best describes your profession?",
        choices=cat_options,
        default="business",
    )

    industry = Prompt.ask("Industry (e.g. Marketing, Finance, Healthcare, Technology)", default="")

    console.print("\n[bold cyan]Seniority Target[/bold cyan]")
    console.print("[dim]What level of roles are you targeting?[/dim]")
    sen_options = list(_SENIORITY_LEVELS.keys())
    for k, v in _SENIORITY_LEVELS.items():
        console.print(f"  [dim]{k}:[/dim] {v}")
    seniority = Prompt.ask("Target seniority", choices=sen_options, default="senior_manager")

    console.print("\n[bold cyan]Scoring Weights[/bold cyan]")
    console.print("[dim]How important is each factor? (high / medium / low)[/dim]")
    skills_w = Prompt.ask("Skills & expertise match", choices=["high", "medium", "low"], default="high")
    exp_w = Prompt.ask("Years of experience", choices=["high", "medium", "low"], default="high")
    seniority_w = Prompt.ask("Seniority level match", choices=["high", "medium", "low"], default="high")
    industry_w = Prompt.ask("Industry/domain alignment", choices=["high", "medium", "low"], default="medium")
    education_w = Prompt.ask("Education & certifications", choices=["high", "medium", "low"], default="medium")

    console.print("\n[bold cyan]Title Filters[/bold cyan]")
    console.print("[dim]Keywords that automatically disqualify a job (junior/entry roles below your level).[/dim]")
    disqualify_raw = Prompt.ask(
        "Disqualify if title contains (comma-separated)",
        default="intern, internship, estagio, estagiario, trainee, junior, assistant, assistente, auxiliar, apprentice"
    )
    disqualify_keywords = [k.strip().lower() for k in disqualify_raw.split(",") if k.strip()]

    target_raw = Prompt.ask(
        "Target title keywords you're looking for (comma-separated, optional)",
        default=""
    )
    target_keywords = [k.strip().lower() for k in target_raw.split(",") if k.strip()]

    prefs = {
        "industry": industry,
        "profession_category": cat,
        "seniority_target": seniority,
        "weight_factors": {
            "skills_match": skills_w,
            "experience_years": exp_w,
            "seniority_match": seniority_w,
            "industry_match": industry_w,
            "education": education_w,
        },
        "disqualify_title_keywords": disqualify_keywords,
        "target_title_keywords": target_keywords,
    }

    if PROFILE_PATH.exists():
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    else:
        profile = {}

    profile["scoring_preferences"] = prefs
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]Scoring preferences saved to {PROFILE_PATH}[/green]")


# ---------------------------------------------------------------------------
# AI Features
# ---------------------------------------------------------------------------

def _setup_ai_features() -> None:
    """Ask about AI scoring/tailoring — optional LLM configuration."""
    console.print(Panel(
        "[bold]Step 4: AI Features (optional)[/bold]\n"
        "An LLM powers job scoring, resume tailoring, and cover letters.\n"
        "Without this, you can still discover and enrich jobs."
    ))

    if not Confirm.ask("Enable AI scoring and resume tailoring?", default=True):
        console.print("[dim]Discovery-only mode. You can configure AI later with [bold]applypilot init[/bold].[/dim]")
        return

    console.print("Supported providers: [bold]Gemini[/bold] (recommended, free tier), OpenAI, local (Ollama/llama.cpp)")
    provider = Prompt.ask(
        "Provider",
        choices=["gemini", "openai", "local"],
        default="gemini",
    )

    env_lines = ["# ApplyPilot configuration", ""]

    if provider == "gemini":
        api_key = Prompt.ask("Gemini API key (from aistudio.google.com)")
        model = Prompt.ask("Model", default="gemini-2.0-flash")
        env_lines.append(f"GEMINI_API_KEY={api_key}")
        env_lines.append(f"LLM_MODEL={model}")
    elif provider == "openai":
        api_key = Prompt.ask("OpenAI API key")
        model = Prompt.ask("Model", default="gpt-4o-mini")
        env_lines.append(f"OPENAI_API_KEY={api_key}")
        env_lines.append(f"LLM_MODEL={model}")
    elif provider == "local":
        url = Prompt.ask("Local LLM endpoint URL", default="http://localhost:8080/v1")
        model = Prompt.ask("Model name", default="local-model")
        env_lines.append(f"LLM_URL={url}")
        env_lines.append(f"LLM_MODEL={model}")

    env_lines.append("")
    ENV_PATH.write_text("\n".join(env_lines), encoding="utf-8")
    console.print(f"[green]AI configuration saved to {ENV_PATH}[/green]")


# ---------------------------------------------------------------------------
# Auto-Apply
# ---------------------------------------------------------------------------

def _setup_auto_apply() -> None:
    """Configure autonomous job application (requires Claude Code CLI)."""
    console.print(Panel(
        "[bold]Step 5: Auto-Apply (optional)[/bold]\n"
        "ApplyPilot can autonomously fill and submit job applications\n"
        "using Claude Code as the browser agent."
    ))

    if not Confirm.ask("Enable autonomous job applications?", default=True):
        console.print("[dim]You can apply manually using the tailored resumes ApplyPilot generates.[/dim]")
        return

    # Check for Claude Code CLI
    if shutil.which("claude"):
        console.print("[green]Claude Code CLI detected.[/green]")
    else:
        console.print(
            "[yellow]Claude Code CLI not found on PATH.[/yellow]\n"
            "Install it from: [bold]https://claude.ai/code[/bold]\n"
            "Auto-apply won't work until Claude Code is installed."
        )

    # Optional: CapSolver for CAPTCHAs
    console.print("\n[dim]Some job sites use CAPTCHAs. CapSolver can handle them automatically.[/dim]")
    if Confirm.ask("Configure CapSolver API key? (optional)", default=False):
        capsolver_key = Prompt.ask("CapSolver API key")
        # Append to existing .env or create
        if ENV_PATH.exists():
            existing = ENV_PATH.read_text(encoding="utf-8")
            if "CAPSOLVER_API_KEY" not in existing:
                ENV_PATH.write_text(
                    existing.rstrip() + f"\nCAPSOLVER_API_KEY={capsolver_key}\n",
                    encoding="utf-8",
                )
        else:
            ENV_PATH.write_text(f"# ApplyPilot configuration\nCAPSOLVER_API_KEY={capsolver_key}\n", encoding="utf-8")
        console.print("[green]CapSolver key saved.[/green]")
    else:
        console.print("[dim]Skipped. Add CAPSOLVER_API_KEY to .env later if needed.[/dim]")


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run_wizard() -> None:
    """Run the full interactive setup wizard."""
    console.print()
    console.print(
        Panel.fit(
            "[bold green]ApplyPilot Setup Wizard[/bold green]\n\n"
            "This will create your configuration at:\n"
            f"  [cyan]{APP_DIR}[/cyan]\n\n"
            "You can re-run this anytime with [bold]applypilot init[/bold].",
            border_style="green",
        )
    )

    ensure_dirs()
    console.print(f"[dim]Created {APP_DIR}[/dim]\n")

    # Step 1: Resume
    _setup_resume()
    console.print()

    # Step 2: Profile
    _setup_profile()
    console.print()

    # Step 3: Search config
    _setup_searches()
    console.print()

    # Step 4: Scoring preferences (profession-aware job scoring)
    _setup_scoring_preferences()
    console.print()

    # Step 5: AI features (optional LLM)
    _setup_ai_features()
    console.print()

    # Step 6: Auto-apply (Claude Code detection)
    _setup_auto_apply()
    console.print()

    # Done — show tier status
    from applypilot.config import get_tier, TIER_LABELS, TIER_COMMANDS

    tier = get_tier()

    tier_lines: list[str] = []
    for t in range(1, 4):
        label = TIER_LABELS[t]
        cmds = ", ".join(f"[bold]{c}[/bold]" for c in TIER_COMMANDS[t])
        if t <= tier:
            tier_lines.append(f"  [green]✓ Tier {t} — {label}[/green]  ({cmds})")
        elif t == tier + 1:
            tier_lines.append(f"  [yellow]→ Tier {t} — {label}[/yellow]  ({cmds})")
        else:
            tier_lines.append(f"  [dim]✗ Tier {t} — {label}  ({cmds})[/dim]")

    unlock_hint = ""
    if tier == 1:
        unlock_hint = "\n[dim]To unlock Tier 2: configure an LLM API key (re-run [bold]applypilot init[/bold]).[/dim]"
    elif tier == 2:
        unlock_hint = "\n[dim]To unlock Tier 3: install Claude Code CLI + Chrome.[/dim]"

    console.print(
        Panel.fit(
            "[bold green]Setup complete![/bold green]\n\n"
            f"[bold]Your tier: Tier {tier} — {TIER_LABELS[tier]}[/bold]\n\n"
            + "\n".join(tier_lines)
            + unlock_hint,
            border_style="green",
        )
    )
