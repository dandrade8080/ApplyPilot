"""ApplyPilot configuration: paths, platform detection, user data."""

import os
import platform
import shutil
from pathlib import Path

# User data directory — all user-specific files live here
APP_DIR = Path(os.environ.get("APPLYPILOT_DIR", Path.home() / ".applypilot"))

# Core paths
DB_PATH = APP_DIR / "applypilot.db"
PROFILE_PATH = APP_DIR / "profile.json"
RESUME_PATH = APP_DIR / "resume.txt"
RESUME_PDF_PATH = APP_DIR / "resume.pdf"
SEARCH_CONFIG_PATH = APP_DIR / "searches.yaml"
ENV_PATH = APP_DIR / ".env"

# Generated output
TAILORED_DIR = APP_DIR / "tailored_resumes"
COVER_LETTER_DIR = APP_DIR / "cover_letters"
LOG_DIR = APP_DIR / "logs"

# Chrome worker isolation
CHROME_WORKER_DIR = APP_DIR / "chrome-workers"
APPLY_WORKER_DIR = APP_DIR / "apply-workers"

# Package-shipped config (YAML registries)
PACKAGE_DIR = Path(__file__).parent
CONFIG_DIR = PACKAGE_DIR / "config"


def get_chrome_path() -> str:
    """Auto-detect Chrome/Chromium executable path, cross-platform.

    Override with CHROME_PATH environment variable.
    """
    env_path = os.environ.get("CHROME_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    system = platform.system()

    if system == "Windows":
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
    elif system == "Darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ]
    else:  # Linux
        candidates = []
        for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

    for c in candidates:
        if c and c.exists():
            return str(c)

    # Fall back to PATH search
    for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return found

    raise FileNotFoundError(
        "Chrome/Chromium not found. Install Chrome or set CHROME_PATH environment variable."
    )


def get_chrome_user_data() -> Path:
    """Default Chrome user data directory, cross-platform."""
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    else:
        return Path.home() / ".config" / "google-chrome"


def ensure_dirs():
    """Create all required directories."""
    for d in [APP_DIR, TAILORED_DIR, COVER_LETTER_DIR, LOG_DIR, CHROME_WORKER_DIR, APPLY_WORKER_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def load_profile() -> dict:
    """Load user profile from ~/.applypilot/profile.json."""
    import json
    if not PROFILE_PATH.exists():
        raise FileNotFoundError(
            f"Profile not found at {PROFILE_PATH}. Run `applypilot init` first."
        )
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def load_scoring_preferences() -> dict:
    """Load scoring preferences from the user's profile, with sensible defaults.

    Returns a dict with keys: industry, profession_category, seniority_target,
    primary_skills, weight_factors, disqualify_title_keywords, target_title_keywords.
    """
    try:
        profile = load_profile()
    except FileNotFoundError:
        profile = {}

    prefs = profile.get("scoring_preferences", {})
    if not prefs:
        return _default_scoring_preferences(profile)

    defaults = _default_scoring_preferences(profile)
    for key in defaults:
        if key not in prefs:
            prefs[key] = defaults[key]

    return prefs


def _default_scoring_preferences(profile: dict) -> dict:
    """Build sensible scoring defaults from whatever profile data exists.

    Detects profession category by checking for tech-specific skill categories
    (programming_languages, frameworks, databases, devops). Supports both the
    new skills_boundary format (primary_skills, tools, certifications, soft_skills)
    and the legacy format (programming_languages, frameworks, tools, databases, etc.).
    """
    exp = profile.get("experience", {})
    skills = profile.get("skills_boundary", {})

    tech_categories = ("programming_languages", "frameworks", "databases", "devops")
    has_tech_skills = any(
        isinstance(skills.get(cat), list) and len(skills.get(cat, [])) > 0
        for cat in tech_categories
    )

    all_skills = []
    for cat in ("primary_skills", "domain_expertise", "certifications",
                "tools", "soft_skills", "programming_languages", "frameworks",
                "databases", "devops", "design_tools", "languages"):
        vals = skills.get(cat, [])
        if isinstance(vals, list):
            all_skills.extend(vals)

    yrs = exp.get("years_of_experience_total", "")

    seniority = "mid"
    try:
        yrs_int = int(yrs)
        if yrs_int >= 15:
            seniority = "executive"
        elif yrs_int >= 10:
            seniority = "director_vp"
        elif yrs_int >= 7:
            seniority = "senior_manager"
        elif yrs_int >= 4:
            seniority = "senior"
        elif yrs_int >= 1:
            seniority = "mid"
    except (ValueError, TypeError):
        pass

    return {
        "industry": profile.get("personal", {}).get("industry", ""),
        "profession_category": "technology" if has_tech_skills else "business",
        "seniority_target": seniority,
        "primary_skills": all_skills[:15],
        "weight_factors": {
            "skills_match": "high",
            "experience_years": "high",
            "industry_match": "medium",
            "seniority_match": "high",
            "education": "medium",
        },
        "disqualify_title_keywords": [
            "intern", "internship", "estágio", "estagiário", "trainee",
            "junior", "assistant", "assistente", "auxiliar", "apprentice",
        ],
        "target_title_keywords": [],
    }


def build_scoring_prompt(resume_text: str, preferences: dict | None = None) -> str:
    """Generate a dynamic scoring prompt based on the user's profile and preferences.

    The prompt guides the LLM to evaluate job fit using criteria that are
    relevant TO THIS SPECIFIC CANDIDATE, not generic software engineering criteria.

    Args:
        resume_text: The candidate's resume text (used to detect profile type).
        preferences: Optional scoring_preferences dict. Loaded from profile if None.

    Returns:
        A complete system prompt string for the LLM scorer.
    """
    if preferences is None:
        preferences = load_scoring_preferences()

    industry = preferences.get("industry", "")
    category = preferences.get("profession_category", "business")
    seniority = preferences.get("seniority_target", "senior")
    primary_skills = preferences.get("primary_skills", [])
    weight_factors = preferences.get("weight_factors", {})

    seniority_labels = {
        "executive": "C-level/VP/Executive",
        "director_vp": "Director/VP/Head",
        "senior_manager": "Senior Manager/Manager",
        "senior": "Senior-level individual contributor",
        "mid": "Mid-level",
        "entry": "Entry-level",
    }
    seniority_label = seniority_labels.get(seniority, "Manager-level")

    base = f"""You are a job fit evaluator. Given a candidate's resume and a job description, score how well the candidate fits the role on a 1-10 scale.

SCORING CRITERIA:
- 9-10: Perfect match. Candidate has direct experience in nearly all required responsibilities and qualifications.
- 7-8: Strong match. Candidate meets most requirements; minor gaps are easily bridged.
- 5-6: Moderate match. Candidate has relevant background but is missing some key requirements.
- 3-4: Weak match. Significant gaps in skills, experience level, or domain knowledge.
- 1-2: Poor match. The role is in a different field, industry, or seniority level entirely.

CANDIDATE PROFILE:
- Target seniority: {seniority_label}
- Target industry: {industry or "Any (open to opportunities across industries)"}
"""

    if primary_skills:
        base += "- Core expertise: " + ", ".join(primary_skills[:10]) + "\n"

    base += "\nIMPORTANT FACTORS (weighted for THIS candidate):\n"

    factor_lines = _build_factor_lines(category, weight_factors, primary_skills, seniority_label)

    base += "\n".join(factor_lines) + "\n"

    base += f"""
CRITICAL SENIORITY RULE:
The candidate targets {seniority_label} roles. If the job title or description
indicates it is clearly BELOW this seniority level (e.g. entry-level, junior,
assistant, intern, trainee, or individual contributor when candidate targets leadership),
score it 1-3 regardless of skill match. A senior professional should not be
recommended for junior positions.

RESPOND IN EXACTLY THIS FORMAT (no other text):
SCORE: [1-10]
KEYWORDS: [comma-separated keywords from the job description that match the candidate's profile]
REASONING: [2-3 sentences explaining the score, mentioning specific matches or gaps]"""

    return base


def _build_factor_lines(category: str, weight_factors: dict, primary_skills: list, seniority_label: str) -> list[str]:
    """Build the IMPORTANT FACTORS section based on profession category."""
    skill_focus = weight_factors.get("skills_match", "high")
    exp_focus = weight_factors.get("experience_years", "high")
    industry_focus = weight_factors.get("industry_match", "medium")
    seniority_focus = weight_factors.get("seniority_match", "high")
    education_focus = weight_factors.get("education", "medium")

    lines = []

    if category == "technology":
        lines.append("- Weight technical skills heavily (programming languages, frameworks, cloud, DevOps)")
        lines.append("- Consider system design and architecture experience")
        lines.append("- Evaluate project complexity and scale (users, throughput, team size)")
        if primary_skills:
            lines.append(f"- Specifically look for: {', '.join(primary_skills[:8])}")

    elif category == "healthcare":
        lines.append("- Weight clinical skills, certifications, and patient care experience heavily")
        lines.append("- Consider medical licenses, board certifications, and specialized training")
        lines.append("- Evaluate clinical setting match (hospital vs clinic vs private practice)")

    elif category == "creative":
        lines.append("- Weight portfolio quality, design tools proficiency, and creative output")
        lines.append("- Consider visual/design skills and creative problem-solving")
        lines.append("- Evaluate brand/agency experience and client-facing work")

    elif category == "education":
        lines.append("- Weight teaching experience, curriculum development, and pedagogical skills")
        lines.append("- Consider certifications, degrees, and specialized training")
        lines.append("- Evaluate classroom management and student engagement experience")

    elif category == "legal":
        lines.append("- Weight bar admission status, practice area specialization, and case experience")
        lines.append("- Consider court experience, transaction volume, and client management")
        lines.append("- Evaluate regulatory and compliance knowledge")

    elif category == "supply_chain":
        lines.append("- Weight supply chain, logistics, procurement, and operations experience")
        lines.append("- Consider ERP systems knowledge (SAP, Oracle, etc.)")
        lines.append("- Evaluate vendor management, inventory optimization, and cost reduction")
        lines.append("- Consider certifications (APICS, CSCMP, Six Sigma, etc.)")

    else:
        lines.append("- Weight domain expertise and industry-specific knowledge heavily")
        lines.append("- Consider leadership, strategy, and business impact")
        lines.append("- Evaluate stakeholder management and cross-functional collaboration")
        if primary_skills:
            lines.append(f"- Core skills to look for: {', '.join(primary_skills[:8])}")

    if exp_focus == "high":
        lines.append("- Years of experience and career progression are critical — weigh them heavily")
    if seniority_focus == "high":
        lines.append(f"- Seniority level must be {seniority_label} or higher — penalize junior/entry roles")
    if industry_focus in ("high", "medium"):
        lines.append("- Consider industry/domain alignment")
    if education_focus == "high":
        lines.append("- Education level and relevant certifications are important")

    return lines


def load_search_config() -> dict:
    """Load search configuration from ~/.applypilot/searches.yaml."""
    import yaml
    if not SEARCH_CONFIG_PATH.exists():
        # Fall back to package-shipped example
        example = CONFIG_DIR / "searches.example.yaml"
        if example.exists():
            return yaml.safe_load(example.read_text(encoding="utf-8"))
        return {}
    return yaml.safe_load(SEARCH_CONFIG_PATH.read_text(encoding="utf-8"))


def load_sites_config() -> dict:
    """Load sites.yaml configuration (sites list, manual_ats, blocked, etc.)."""
    import yaml
    path = CONFIG_DIR / "sites.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def is_manual_ats(url: str | None) -> bool:
    """Check if a URL routes through an ATS that requires manual application."""
    if not url:
        return False
    sites_cfg = load_sites_config()
    domains = sites_cfg.get("manual_ats", [])
    url_lower = url.lower()
    return any(domain in url_lower for domain in domains)


def load_blocked_sites() -> tuple[set[str], list[str]]:
    """Load blocked sites and URL patterns from sites.yaml.

    Returns:
        (blocked_site_names, blocked_url_patterns)
    """
    cfg = load_sites_config()
    blocked = cfg.get("blocked", {})
    sites = set(blocked.get("sites", []))
    patterns = blocked.get("url_patterns", [])
    return sites, patterns


def load_blocked_sso() -> list[str]:
    """Load blocked SSO domains from sites.yaml."""
    cfg = load_sites_config()
    return cfg.get("blocked_sso", [])


def load_base_urls() -> dict[str, str | None]:
    """Load site base URLs for URL resolution from sites.yaml."""
    cfg = load_sites_config()
    return cfg.get("base_urls", {})


# ---------------------------------------------------------------------------
# Default values — referenced across modules instead of magic numbers
# ---------------------------------------------------------------------------

DEFAULTS = {
    "min_score": 7,
    "max_apply_attempts": 3,
    "max_tailor_attempts": 5,
    "poll_interval": 60,
    "apply_timeout": 300,
    "viewport": "1280x900",
}


def load_env():
    """Load environment variables from ~/.applypilot/.env and CWD .env."""
    from dotenv import load_dotenv
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
    load_dotenv()


# ---------------------------------------------------------------------------
# Tier system — feature gating by installed dependencies
# ---------------------------------------------------------------------------

TIER_LABELS = {
    1: "Discovery",
    2: "AI Scoring & Tailoring",
    3: "Full Auto-Apply",
}

TIER_COMMANDS: dict[int, list[str]] = {
    1: ["init", "run discover", "run enrich", "status", "dashboard"],
    2: ["run score", "run tailor", "run cover", "run pdf", "run"],
    3: ["apply"],
}


def get_tier() -> int:
    """Detect the current tier based on available dependencies.

    Tier 1 (Discovery):            Python + pip
    Tier 2 (AI Scoring & Tailoring): + LLM API key
    Tier 3 (Full Auto-Apply):       + Claude Code CLI + Chrome
    """
    load_env()

    has_llm = any(os.environ.get(k) for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "LLM_URL"))
    if not has_llm:
        return 1

    has_claude = shutil.which("claude") is not None
    try:
        get_chrome_path()
        has_chrome = True
    except FileNotFoundError:
        has_chrome = False

    if has_claude and has_chrome:
        return 3

    return 2


def check_tier(required: int, feature: str) -> None:
    """Raise SystemExit with a clear message if the current tier is too low.

    Args:
        required: Minimum tier needed (1, 2, or 3).
        feature: Human-readable description of the feature being gated.
    """
    current = get_tier()
    if current >= required:
        return

    from rich.console import Console
    _console = Console(stderr=True)

    missing: list[str] = []
    if required >= 2 and not any(os.environ.get(k) for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "LLM_URL")):
        missing.append("LLM API key — run [bold]applypilot init[/bold] or set GEMINI_API_KEY")
    if required >= 3:
        if not shutil.which("claude"):
            missing.append("Claude Code CLI — install from [bold]https://claude.ai/code[/bold]")
        try:
            get_chrome_path()
        except FileNotFoundError:
            missing.append("Chrome/Chromium — install or set CHROME_PATH")

    _console.print(
        f"\n[red]'{feature}' requires {TIER_LABELS.get(required, f'Tier {required}')} (Tier {required}).[/red]\n"
        f"Current tier: {TIER_LABELS.get(current, f'Tier {current}')} (Tier {current})."
    )
    if missing:
        _console.print("\n[yellow]Missing:[/yellow]")
        for m in missing:
            _console.print(f"  - {m}")
    _console.print()
    raise SystemExit(1)
