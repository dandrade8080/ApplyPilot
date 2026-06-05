"""LinkedIn profile scraper for ApplyPilot.

Fetches a public LinkedIn profile URL and extracts structured data.
Uses HTML meta tags + LLM on visible text for richer extraction.
"""

import json
import logging
import re

import httpx
from bs4 import BeautifulSoup

from applypilot.llm import get_client

log = logging.getLogger(__name__)

_LINKEDIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_TIMEOUT = 30

# ---------------------------------------------------------------------------
# HTML extraction helpers
# ---------------------------------------------------------------------------

_CHUNK_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)


def _visible_text(html: str) -> str:
    """Strip script/style/noscript tags to get visible page text."""
    return _CHUNK_RE.sub("", html)


def _extract_from_meta(soup: BeautifulSoup) -> dict:
    """Extract profile data from meta tags, title, and JSON-LD."""
    result: dict = {}
    text = _visible_text(str(soup))

    # --- Title ---
    t = soup.find("title")
    if t:
        result["og_title"] = t.get_text(strip=True)

    # --- First name / last name from OG ---
    fn_tag = soup.find("meta", attrs={"property": "profile:first_name"})
    ln_tag = soup.find("meta", attrs={"property": "profile:last_name"})
    if fn_tag and ln_tag:
        result["name"] = f"{fn_tag.get('content', '')} {ln_tag.get('content', '')}".strip()

    # --- Fallback name from title ---
    if not result.get("name") and result.get("og_title"):
        name_match = re.match(r"^(.+?)\s*[-|]", result["og_title"])
        if name_match:
            result["name"] = name_match.group(1).strip()

    # --- Meta description (richest data source) ---
    md = soup.find("meta", attrs={"name": "description"})
    desc = md.get("content", "") if md else ""
    result["meta_description"] = desc[:1000]

    if desc:
        # Extract headline: first sentence of the description
        headline_match = re.match(r"^(.+?)(?:\.\s|•|\s-\s)", desc)
        if headline_match:
            result["headline"] = headline_match.group(1).strip()
        else:
            sentences = desc.split(".")
            if sentences:
                result["headline"] = sentences[0].strip()

        # Location: after "Location:"
        loc_match = re.search(r"Location:\s*([^•]+)", desc)
        if loc_match:
            result["location"] = loc_match.group(1).strip()

        # Current company: after "Experience:"
        exp_match = re.search(r"Experience:\s*([^•]+)", desc)
        if exp_match:
            result["current_company"] = exp_match.group(1).strip()

        # Education: after "Education:"
        edu_match = re.search(r"Education:\s*([^•]+)", desc)
        if edu_match:
            result["education"] = edu_match.group(1).strip()

    # --- Extract text sections from visible page (About section) ---
    # LinkedIn public pages often have "About" as visible text
    about_match = re.search(
        r"(?:About|Sobre)\s*\n(.+?)(?:\n\n|\n(?:Experience|Experiência|Education|Skills|Idiomas)|\Z)",
        text, re.DOTALL | re.IGNORECASE
    )
    if about_match:
        about_text = about_match.group(1).strip()
        if len(about_text) > 20:
            result["about"] = about_text[:2000]

    return result


# ---------------------------------------------------------------------------
# LLM enrichment (lightweight, only on visible text)
# ---------------------------------------------------------------------------


def _enrich_with_llm(meta_desc: str, visible: str) -> dict:
    """Use LLM to extract structured profile data from visible text only."""
    client = get_client()

    input_text = f"META DESCRIPTION:\n{meta_desc[:800]}\n\n---\n\nVISIBLE PAGE TEXT:\n{visible[:4000]}"

    prompt = f"""Extract LinkedIn profile information from the text below.

Return a JSON object with these fields (empty string if missing):
- "name": full name
- "headline": professional headline
- "location": city/region
- "about": summary/about section
- "skills": list of skill keywords found
- "experience": list of {{company, role, dates, description}}
- "education": list of {{school, degree, field, dates}}

Return ONLY valid JSON, no markdown, no explanation.

TEXT:
{input_text}"""

    try:
        result = client.ask(prompt, temperature=0.1, max_tokens=2048)
        result = result.strip()
        if result.startswith("```"):
            result = result.split("\n", 1)[1]
            result = result.rsplit("```", 1)[0]
        return json.loads(result)
    except Exception as e:
        log.warning("LLM enrichment failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scrape_profile(url: str) -> dict:
    """Scrape a LinkedIn profile URL and return structured data.

    Returns dict with: name, headline, location, about, skills,
    current_company, education, linkedin_url.
    """
    normalized = url.split("?")[0].rstrip("/")

    html = _fetch_html(normalized)
    if not html:
        return {"linkedin_url": normalized, "error": "Could not fetch profile page"}

    soup = BeautifulSoup(html, "html.parser")
    result = _extract_from_meta(soup)
    result["linkedin_url"] = normalized

    visible = _visible_text(html)

    # LLM enrichment on visible text (lightweight)
    if result.get("meta_description"):
        llm_data = _enrich_with_llm(result.get("meta_description", ""), visible)

        if llm_data:
            for key in ("name", "headline", "location", "about", "skills", "experience", "education"):
                if llm_data.get(key):
                    result[key] = llm_data[key]

    # Ensure all keys exist
    result.setdefault("name", "")
    result.setdefault("headline", "")
    result.setdefault("location", "")
    result.setdefault("about", "")
    result.setdefault("skills", [])
    result.setdefault("experience", [])
    result.setdefault("current_company", "")
    result.setdefault("education", "")
    # Remove raw HTML data from result
    result.pop("meta_description", None)
    result.pop("og_title", None)

    log.info(
        "LinkedIn scrape: name=%s, location=%s, skills=%d, experience=%d",
        result.get("name", "?"), result.get("location", "?"),
        len(result.get("skills", [])), len(result.get("experience", []))
    )

    return result


def _fetch_html(url: str) -> str | None:
    """Fetch page HTML with a browser-like User-Agent."""
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": _LINKEDIN_UA},
            follow_redirects=True,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        log.warning("Failed to fetch %s: %s", url, e)
        return None
