"""Web routes for ApplyPilot dashboard."""

import json
import os
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from applypilot.config import (
    APP_DIR,
    COVER_LETTER_DIR,
    DB_PATH,
    ENV_PATH,
    PROFILE_PATH,
    RESUME_PATH,
    TAILORED_DIR,
    load_env,
    load_profile,
)
from applypilot.database import get_connection, get_jobs_by_stage, get_stats
from applypilot.pipeline import STAGE_META, _STAGE_RUNNERS
from applypilot.web.linkedin import scrape_profile

bp = Blueprint("dashboard", __name__, template_folder="templates")

# Background pipeline runner state
_pipeline_thread: threading.Thread | None = None
_pipeline_cancel = threading.Event()
_pipeline_status = {"stage": "idle", "message": "", "progress": 0, "total": 0}


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------

def _read_profile() -> dict:
    try:
        return load_profile()
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _flatten_profile(nested: dict) -> dict:
    """Convert nested wizard format to flat format for dashboard templates."""
    p = nested.get("personal", {})
    wa = nested.get("work_authorization", {})
    exp = nested.get("experience", {})
    sb = nested.get("skills_boundary", {})
    rf = nested.get("resume_facts", {})
    av = nested.get("availability", {})
    comp = nested.get("compensation", {})
    eeo = nested.get("eeo_voluntary", {})

    tools = sb.get("tools", [])
    languages = sb.get("languages", [])
    all_skills = list(dict.fromkeys(tools + languages))

    exp_lines = []
    for e in nested.get("experience_list", []):
        parts = [e.get("company", ""), e.get("role", ""), e.get("period", ""), e.get("description", "")]
        exp_lines.append(" | ".join(p for p in parts if p))

    edu_lines = []
    for e in nested.get("education_list", []):
        parts = [e.get("institution", ""), e.get("degree", ""), e.get("field", ""), e.get("period", "")]
        edu_lines.append(" | ".join(p for p in parts if p))

    city = p.get("city", "")
    state = p.get("province_state", "")
    location = f"{city}, {state}" if city and state else city or state or ""

    return {
        "name": p.get("full_name", ""),
        "email": p.get("email", ""),
        "phone": p.get("phone", ""),
        "location": location,
        "linkedin": p.get("linkedin_url", ""),
        "github": p.get("github_url", ""),
        "portfolio": p.get("portfolio_url", ""),
        "headline": exp.get("current_job_title", ""),
        "summary": nested.get("summary", "") or nested.get("about", "") or "",
        "about": nested.get("about", "") or nested.get("summary", "") or "",
        "skills": nested.get("skills", all_skills),
        "experience_text": nested.get("experience_text", "\n\n".join(exp_lines)),
        "education_text": nested.get("education_text", "\n\n".join(edu_lines)),
        "_nested": nested,
    }


def _read_tailored_resume(job_url: str) -> str | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT tailored_resume_path FROM jobs WHERE url = ?", (job_url,)
    ).fetchone()
    if row and row["tailored_resume_path"]:
        path = Path(row["tailored_resume_path"])
        if path.exists():
            return path.read_text(encoding="utf-8")
    return None


def _read_cover_letter(job_url: str) -> str | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT cover_letter_path FROM jobs WHERE url = ?", (job_url,)
    ).fetchone()
    if row and row["cover_letter_path"]:
        path = Path(row["cover_letter_path"])
        if path.exists():
            return path.read_text(encoding="utf-8")
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@bp.route("/")
def index():
    """Dashboard home — pipeline overview with stats."""
    from applypilot.alerts import get_alert_count
    from applypilot.apply_queue import get_queue_counts
    stats = get_stats()
    stats["alert_count"] = get_alert_count()
    stats["queue_counts"] = get_queue_counts()
    return render_template("dashboard.html", stats=stats)


@bp.route("/profile")
def profile():
    """View user profile."""
    data = _read_profile()
    flat = _flatten_profile(data) if data else data
    resume = ""
    if RESUME_PATH.exists():
        try:
            resume = RESUME_PATH.read_text(encoding="utf-8")
        except (UnicodeDecodeError, LookupError):
            try:
                resume = RESUME_PATH.read_text(encoding="latin-1")
            except Exception:
                resume = ""
    return render_template("profile.html", profile=flat, resume=resume)


@bp.route("/profile/edit", methods=["GET", "POST"])
def profile_edit():
    """Edit user profile."""
    if request.method == "POST":
        skills_raw = request.form.get("skills", "")
        skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
        location_raw = request.form.get("location", "")
        loc_parts = [p.strip() for p in location_raw.split(",")] if location_raw else ["", ""]
        city = loc_parts[0] if len(loc_parts) > 0 else ""
        state = loc_parts[1] if len(loc_parts) > 1 else ""

        profile = {
            "personal": {
                "full_name": request.form.get("name", ""),
                "preferred_name": "",
                "email": request.form.get("email", ""),
                "password": "",
                "phone": request.form.get("phone", ""),
                "address": "",
                "city": city,
                "province_state": state,
                "country": "Brasil",
                "postal_code": "",
                "linkedin_url": request.form.get("linkedin", ""),
                "github_url": request.form.get("github", ""),
                "portfolio_url": request.form.get("portfolio", ""),
                "website_url": "",
            },
            "work_authorization": {
                "legally_authorized_to_work": "Yes",
                "require_sponsorship": "No",
                "work_permit_type": "Citizen",
            },
            "availability": {
                "earliest_start_date": "Immediately",
                "available_for_full_time": "Yes",
                "available_for_contract": "Yes",
            },
            "compensation": {
                "salary_expectation": "300000",
                "salary_currency": "BRL",
                "salary_range_min": "300000",
                "salary_range_max": "360000",
                "currency_conversion_note": "Valores anuais em BRL (R$). R$ 25.000-30.000/mês x 12 meses.",
            },
            "experience": {
                "years_of_experience_total": "20",
                "education_level": "MBA Executivo - SDA Bocconi",
                "current_job_title": request.form.get("headline", ""),
                "current_company": "",
                "target_role": request.form.get("headline", ""),
            },
            "skills_boundary": {
                "programming_languages": [],
                "frameworks": [],
                "tools": skills,
                "databases": [],
                "devops": [],
                "languages": [],
            },
            "resume_facts": {
                "preserved_companies": [],
                "preserved_projects": [],
                "preserved_school": "",
                "real_metrics": [],
            },
            "eeo_voluntary": {
                "gender": "Decline to self-identify",
                "race_ethnicity": "Decline to self-identify",
                "veteran_status": "I am not a protected veteran",
                "disability_status": "I do not wish to answer",
            },
        }

        summary = request.form.get("summary", "")
        if summary:
            profile["summary"] = summary
            profile["about"] = summary

        exp_text = request.form.get("experience", "")
        if exp_text:
            profile["experience_text"] = exp_text
        edu_text = request.form.get("education", "")
        if edu_text:
            profile["education_text"] = edu_text

        PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
        if request.form.get("resume"):
            RESUME_PATH.write_text(request.form["resume"], encoding="utf-8")
        flat = _flatten_profile(profile)
        return render_template("profile_edit.html", profile=flat, saved=True)
    data = _read_profile()
    flat = _flatten_profile(data) if data else data
    return render_template("profile_edit.html", profile=flat, saved=False)


@bp.route("/profile/import-linkedin", methods=["POST"])
def profile_import_linkedin():
    """Import profile data from a LinkedIn URL."""
    url = request.form.get("linkedin_url", "").strip()
    if not url:
        return jsonify({"error": "No LinkedIn URL provided"}), 400

    data = scrape_profile(url)
    if data.get("error"):
        return jsonify({"error": data["error"]}), 400

    return jsonify(data)


@bp.route("/jobs")
def jobs():
    """List all jobs, filterable by stage and score."""
    stage = request.args.get("stage", "discovered")
    min_score = request.args.get("min_score", type=int)
    limit = request.args.get("limit", 200, type=int)
    jobs_list = get_jobs_by_stage(stage=stage, min_score=min_score, limit=limit)

    stages = [
        ("discovered", "Discovered"),
        ("pending_detail", "Pending Enrichment"),
        ("enriched", "Enriched"),
        ("pending_score", "Pending Score"),
        ("scored", "Scored"),
        ("pending_tailor", "Pending Tailor"),
        ("tailored", "Tailored"),
        ("pending_apply", "Ready to Apply"),
        ("applied", "Applied"),
    ]
    return render_template("jobs.html", jobs=jobs_list, stages=stages, current_stage=stage)


@bp.route("/jobs/<path:job_url>")
def job_detail(job_url: str):
    """View a single job with full details."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM jobs WHERE url = ?", (job_url,)).fetchone()
    if not row:
        return render_template("job_detail.html", job=None, error="Job not found.")

    columns = row.keys()
    job = dict(zip(columns, row))
    tailored = _read_tailored_resume(job_url)
    cover = _read_cover_letter(job_url)
    return render_template("job_detail.html", job=job, tailored=tailored, cover=cover, error=None)


@bp.route("/pipeline")
def pipeline():
    """Pipeline overview — run stages and view progress."""
    stats = get_stats()
    stages = []
    for name, meta in STAGE_META.items():
        stages.append({"name": name, "desc": meta["desc"]})
    return render_template("pipeline.html", stats=stats, stages=stages)


@bp.route("/config")
def config_view():
    """View and edit configuration."""
    load_env()
    env_vars = {}
    for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "LLM_URL", "LLM_MODEL", "CAPSOLVER_API_KEY"):
        val = os.environ.get(key, "")
        env_vars[key] = val[:8] + "..." if val and len(val) > 10 else val

    config_data = {
        "app_dir": str(APP_DIR),
        "db_path": str(DB_PATH),
        "profile_path": str(PROFILE_PATH),
        "resume_path": str(RESUME_PATH),
        "tailored_dir": str(TAILORED_DIR),
        "cover_letter_dir": str(COVER_LETTER_DIR),
    }

    env_content = ""
    if ENV_PATH.exists():
        env_content = ENV_PATH.read_text(encoding="utf-8")

    return render_template("config.html", env_vars=env_vars, config=config_data, env_content=env_content)


# ---------------------------------------------------------------------------
# Knowledge Base (Web UI)
# ---------------------------------------------------------------------------


@bp.route("/knowledge")
def knowledge_page():
    from applypilot.knowledge import get_all_knowledge
    entries = get_all_knowledge()
    return render_template("knowledge.html", entries=entries)


# ---------------------------------------------------------------------------
# Alerts (Web UI)
# ---------------------------------------------------------------------------


@bp.route("/alerts")
def alerts_page():
    from applypilot.alerts import get_pending_alerts, get_all_alerts
    pending = get_pending_alerts()
    all_alerts = get_all_alerts()
    return render_template("alerts.html", pending=pending, all_alerts=all_alerts)


# ---------------------------------------------------------------------------
# Apply Queue (Web UI)
# ---------------------------------------------------------------------------


@bp.route("/apply-queue")
def apply_queue_page():
    from applypilot.apply_queue import get_queue, get_queue_counts
    queue = get_queue()
    counts = get_queue_counts()
    return render_template("apply_queue.html", queue=queue, counts=counts)


# ---------------------------------------------------------------------------
# API endpoints (JSON)
# ---------------------------------------------------------------------------


@bp.route("/api/stats")
def api_stats():
    return jsonify(get_stats())


@bp.route("/api/jobs")
def api_jobs():
    stage = request.args.get("stage", "discovered")
    min_score = request.args.get("min_score", type=int)
    limit = request.args.get("limit", 200, type=int)
    jobs_list = get_jobs_by_stage(stage=stage, min_score=min_score, limit=limit)
    return jsonify(jobs_list)


# -- Start Applying (composite: pipeline + enqueue + process) ----------------


@bp.route("/api/start-applying", methods=["POST"])
def api_start_applying():
    """Run full pipeline, enqueue eligible jobs, and start processing.

    This is the main 'Start Applying' button:
    1. Run all pipeline stages (discover → enrich → score → tailor → cover → pdf)
    2. Enqueue all ready-to-apply jobs (score >= 7, tailored)
    3. Start background worker to process the queue
    """
    global _pipeline_thread, _pipeline_cancel
    body = request.get_json(silent=True) or {}
    min_score = body.get("min_score", 7)
    max_jobs = body.get("max_jobs", 10)
    skip_pipeline = body.get("skip_pipeline", False)

    if _pipeline_thread and _pipeline_thread.is_alive():
        return jsonify({"error": "Pipeline already running"}), 409

    _pipeline_cancel.clear()

    def _run():
        global _pipeline_status
        from applypilot.database import get_connection
        from applypilot.apply_queue import enqueue_job, dequeue_next, complete_queue_entry
        from applypilot.apply.engine import apply_to_job
        from applypilot.config import load_profile
        import logging

        logger = logging.getLogger(__name__)

        def _count_pending(stage: str) -> int:
            """Count pending work items for a given stage."""
            conn2 = get_connection()
            sqls = {
                "enrich": "SELECT COUNT(*) FROM jobs WHERE detail_scraped_at IS NULL",
                "score": "SELECT COUNT(*) FROM jobs WHERE full_description IS NOT NULL AND fit_score IS NULL",
                "tailor": "SELECT COUNT(*) FROM jobs WHERE fit_score >= ? AND full_description IS NOT NULL AND tailored_resume_path IS NULL AND COALESCE(tailor_attempts, 0) < 5",
                "cover": "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL AND (cover_letter_path IS NULL OR cover_letter_path = '') AND COALESCE(cover_attempts, 0) < 5",
                "pdf": "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL AND tailored_resume_path LIKE '%.txt'",
            }
            sql = sqls.get(stage)
            if not sql:
                return 0
            if "?" in sql:
                return conn2.execute(sql, (min_score,)).fetchone()[0]
            return conn2.execute(sql).fetchone()[0]

        def _count_pending_after(stage: str) -> int:
            """Count remaining pending work after a stage runs."""
            return _count_pending(stage)

        # Stage 1: Pipeline (skip if user only wants to apply to ready jobs)
        if not skip_pipeline:
            stages = ["discover", "enrich", "score", "tailor", "cover", "pdf"]
            for stage in stages:
                if _pipeline_cancel.is_set():
                    _pipeline_status["stage"] = "cancelled"
                    _pipeline_status["message"] = "Cancelado pelo usuário"
                    break
                _pipeline_status["stage"] = "pipeline"
                pending = _count_pending(stage)
                _pipeline_status["total"] = pending
                _pipeline_status["progress"] = 0
                if pending == 0 and stage != "discover":
                    _pipeline_status["message"] = f"Estágio {stage}: nada pendente"
                    continue
                _pipeline_status["message"] = f"Executando estágio: {stage} ({pending} pendentes)"
                runner = _STAGE_RUNNERS.get(stage)
                if runner:
                    try:
                        kwargs = {}
                        if stage in ("tailor", "cover"):
                            kwargs["min_score"] = min_score
                        runner(**kwargs)
                    except Exception as e:
                        logger.exception("Pipeline stage %s failed", stage)
                # Update progress after stage completes
                remaining = _count_pending_after(stage)
                done = max(0, pending - remaining)
                _pipeline_status["progress"] = done

            if _pipeline_cancel.is_set():
                return
        else:
            _pipeline_status["message"] = "Pipeline ignorado, enfileirando vagas prontas..."

        # Stage 2: Enqueue eligible jobs (skip Indeed — not supported)
        _pipeline_status["stage"] = "enqueue"
        _pipeline_status["message"] = "Enfileirando vagas elegíveis..."
        conn = get_connection()
        rows = conn.execute(
            "SELECT url, title, site FROM jobs "
            "WHERE fit_score >= ? AND tailored_resume_path IS NOT NULL "
            "AND (applied_at IS NULL OR apply_error IS NOT NULL) "
            "AND (site IS NULL OR site != 'indeed') "
            "LIMIT 50", (min_score,)
        ).fetchall()

        qids = []
        for r in rows:
            qid = enqueue_job(r["url"], r["title"], site=r["site"] or "")
            qids.append(qid)

        _pipeline_status["total"] = len(qids)

        if not qids:
            _pipeline_status["stage"] = "done"
            _pipeline_status["message"] = "Nenhuma vaga elegível para aplicar"
            return

        # Stage 3: Process queued jobs
        _pipeline_status["stage"] = "applying"
        _pipeline_status["progress"] = 0
        profile = load_profile()
        processed = 0

        while processed < max_jobs:
            if _pipeline_cancel.is_set():
                _pipeline_status["message"] = "Cancelado durante aplicação"
                break
            entry = dequeue_next()
            if not entry:
                break
            _pipeline_status["progress"] = processed + 1
            _pipeline_status["message"] = "Aplicando vaga %d de %d" % (
                processed + 1, min(max_jobs, _pipeline_status["total"]))

            row = conn.execute(
                "SELECT * FROM jobs WHERE url = ?", (entry["job_url"],)
            ).fetchone()
            if not row:
                complete_queue_entry(entry["id"],
                                     {"status": "failed", "error": "job_not_found"})
                processed += 1
                continue

            # Skip Indeed jobs — not supported
            site = (row["site"] or "").lower()
            if site == "indeed":
                complete_queue_entry(entry["id"],
                    {"status": "failed", "error": "indeed_nao_suportado"})
                processed += 1
                continue

            # Run with timeout to avoid hanging forever
            from concurrent.futures import ThreadPoolExecutor, TimeoutError
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(apply_to_job, dict(row), profile, dry_run=False)
            try:
                result = future.result(timeout=300)  # 5 min timeout per job
            except TimeoutError:
                result = {"status": "failed", "error": "timeout_5min"}
            except Exception as e:
                result = {"status": "failed", "error": str(e)[:200]}
            finally:
                executor.shutdown(wait=False)

            complete_queue_entry(entry["id"], result)
            _pipeline_status["message"] = "Vaga %d/%d: %s" % (
                processed + 1, min(max_jobs, _pipeline_status["total"]),
                "OK" if result.get("status") == "applied" else "Falha")
            processed += 1
            time.sleep(3)  # Let Chrome shut down before next job

        _pipeline_status["stage"] = "done"
        _pipeline_status["message"] = f"Processadas {processed} candidaturas"

    _pipeline_thread = threading.Thread(target=_run, daemon=True)
    _pipeline_thread.start()
    return jsonify({"status": "started"})


# -- Pipeline API ------------------------------------------------------------


@bp.route("/api/pipeline/run", methods=["POST"])
def api_pipeline_run():
    """Start one or more pipeline stages in a background thread."""
    global _pipeline_thread, _pipeline_cancel
    body = request.get_json(silent=True) or {}
    stages = body.get("stages", ["discover", "enrich", "score", "tailor", "cover", "pdf"])
    workers = body.get("workers", 1)

    if _pipeline_thread and _pipeline_thread.is_alive():
        return jsonify({"error": "Pipeline already running"}), 409

    _pipeline_cancel.clear()

    def _run():
        from applypilot.database import get_connection
        now = __import__("datetime").datetime.now().isoformat()
        for stage in stages:
            if _pipeline_cancel.is_set():
                break
            runner = _STAGE_RUNNERS.get(stage)
            if runner:
                try:
                    kwargs = {}
                    if stage in ("tailor", "cover"):
                        kwargs["min_score"] = 7
                    if stage == "discover":
                        kwargs["workers"] = workers
                    if stage == "enrich":
                        kwargs["workers"] = workers
                    runner(**kwargs)
                except Exception as e:
                    pass

    _pipeline_thread = threading.Thread(target=_run, daemon=True)
    _pipeline_thread.start()
    return jsonify({"status": "started", "stages": stages})


@bp.route("/api/pipeline/cancel", methods=["POST"])
def api_pipeline_cancel():
    """Cancel the running pipeline."""
    global _pipeline_cancel
    _pipeline_cancel.set()
    return jsonify({"status": "cancelled"})


@bp.route("/api/pipeline/status")
def api_pipeline_status():
    global _pipeline_thread, _pipeline_status
    running = _pipeline_thread is not None and _pipeline_thread.is_alive()
    return jsonify({
        "running": running,
        "stage": _pipeline_status.get("stage", "idle"),
        "message": _pipeline_status.get("message", ""),
        "progress": _pipeline_status.get("progress", 0),
        "total": _pipeline_status.get("total", 0),
    })


# -- Knowledge API -----------------------------------------------------------


@bp.route("/api/knowledge", methods=["GET"])
def api_knowledge_list():
    from applypilot.knowledge import get_all_knowledge, search_knowledge
    query = request.args.get("q", "")
    if query:
        results = search_knowledge(query)
    else:
        results = get_all_knowledge()
    return jsonify(results)


@bp.route("/api/knowledge", methods=["POST"])
def api_knowledge_add():
    from applypilot.knowledge import save_knowledge
    body = request.get_json(silent=True) or {}
    q = body.get("question", "")
    a = body.get("answer", "")
    if not q or not a:
        return jsonify({"error": "question and answer required"}), 400
    kid = save_knowledge(q, a, source="manual", confidence=1.0,
                         context_tags=body.get("context_tags", ""))
    return jsonify({"id": kid, "status": "saved"})


@bp.route("/api/knowledge/<int:kid>", methods=["DELETE"])
def api_knowledge_delete(kid: int):
    from applypilot.knowledge import delete_knowledge
    ok = delete_knowledge(kid)
    return jsonify({"deleted": ok})


# -- Alerts API --------------------------------------------------------------


@bp.route("/api/alerts")
def api_alerts():
    from applypilot.alerts import get_pending_alerts, get_all_alerts
    return jsonify({
        "pending": get_pending_alerts(),
        "all": get_all_alerts(),
    })


@bp.route("/api/alerts/<int:aid>/answer", methods=["POST"])
def api_alerts_answer(aid: int):
    from applypilot.alerts import answer_alert
    body = request.get_json(silent=True) or {}
    answer = body.get("answer", "")
    if not answer:
        return jsonify({"error": "answer required"}), 400
    ok = answer_alert(aid, answer)
    return jsonify({"answered": ok})


@bp.route("/api/alerts/<int:aid>/dismiss", methods=["POST"])
def api_alerts_dismiss(aid: int):
    from applypilot.alerts import dismiss_alert
    ok = dismiss_alert(aid)
    return jsonify({"dismissed": ok})


@bp.route("/api/alerts/count")
def api_alerts_count():
    from applypilot.alerts import get_alert_count
    return jsonify({"count": get_alert_count()})


# -- Apply Queue API ---------------------------------------------------------


@bp.route("/api/apply-queue", methods=["GET"])
def api_apply_queue():
    from applypilot.apply_queue import get_queue, get_queue_counts
    return jsonify({
        "queue": get_queue(),
        "counts": get_queue_counts(),
    })


@bp.route("/api/apply-queue/enqueue", methods=["POST"])
def api_apply_enqueue():
    from applypilot.apply_queue import enqueue_job
    body = request.get_json(silent=True) or {}
    job_id = body.get("job_id", "")
    job_url = body.get("job_url", "")
    job_title = body.get("job_title", "")
    site = body.get("site", "")
    if not job_id:
        return jsonify({"error": "job_id required"}), 400
    qid = enqueue_job(job_url, job_title, job_id=job_id, site=site)
    return jsonify({"queue_id": qid})


@bp.route("/api/apply-queue/enqueue-batch", methods=["POST"])
def api_apply_enqueue_batch():
    from applypilot.apply_queue import enqueue_job
    from applypilot.database import get_connection
    body = request.get_json(silent=True) or {}
    min_score = body.get("min_score", 7)
    limit = body.get("limit", 50)

    conn = get_connection()
    rows = conn.execute(
        "SELECT url, title, site FROM jobs "
        "WHERE fit_score >= ? AND (applied_at IS NULL OR apply_error IS NOT NULL) "
        "AND tailored_resume_path IS NOT NULL "
        "LIMIT ?", (min_score, limit)
    ).fetchall()

    ids = []
    for r in rows:
        qid = enqueue_job(r["url"], r["title"], site=r["site"] or "")
        ids.append(qid)
        ids.append(qid)
    return jsonify({"enqueued": len(ids), "queue_ids": ids})


@bp.route("/api/apply-queue/<int:qid>/cancel", methods=["POST"])
def api_apply_cancel(qid: int):
    from applypilot.apply_queue import cancel_queue_entry
    ok = cancel_queue_entry(qid)
    return jsonify({"cancelled": ok})


@bp.route("/api/apply-queue/clear", methods=["POST"])
def api_apply_clear():
    from applypilot.apply_queue import clear_queue
    status = request.args.get("status", "")
    cleared = clear_queue(status)
    return jsonify({"cleared": cleared})


@bp.route("/api/apply-queue/process", methods=["POST"])
def api_apply_process():
    """Start processing the apply queue in a background thread."""
    from applypilot.apply_queue import dequeue_next, complete_queue_entry
    from applypilot.apply.engine import apply_to_job
    from applypilot.config import load_profile
    from applypilot.database import get_connection

    body = request.get_json(silent=True) or {}
    max_jobs = body.get("max_jobs", 5)
    dry_run = body.get("dry_run", False)

    profile = load_profile()

    def _worker():
        processed = 0
        while processed < max_jobs:
            entry = dequeue_next()
            if not entry:
                break

            conn = get_connection()
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (entry["job_id"],)
            ).fetchone()
            if not row:
                complete_queue_entry(entry["id"], {"status": "failed", "error": "job_not_found"})
                processed += 1
                continue

            job = dict(row)
            try:
                result = apply_to_job(job, profile, dry_run=dry_run)
            except Exception as e:
                import logging
                logging.exception("Apply worker error for %s", entry["job_id"])
                result = {"status": "failed", "error": str(e)[:200]}

            complete_queue_entry(entry["id"], result)
            processed += 1

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return jsonify({"status": "processing", "max_jobs": max_jobs})


# ---------------------------------------------------------------------------
# Filter config (searches.yaml)
# ---------------------------------------------------------------------------


@bp.route("/filters")
def filters_page():
    from applypilot.config import SEARCH_CONFIG_PATH
    import yaml
    if SEARCH_CONFIG_PATH.exists():
        with open(SEARCH_CONFIG_PATH, "r", encoding="utf-8") as f:
            filters = yaml.safe_load(f)
    else:
        filters = {}
    return render_template("filters.html", filters=filters)


@bp.route("/api/filters", methods=["GET", "POST"])
def api_filters():
    from applypilot.config import SEARCH_CONFIG_PATH
    import yaml

    if request.method == "GET":
        if SEARCH_CONFIG_PATH.exists():
            with open(SEARCH_CONFIG_PATH, "r", encoding="utf-8") as f:
                return jsonify(yaml.safe_load(f) or {})
        return jsonify({})

    # POST: save
    body = request.get_json(silent=True) or {}

    config = {
        "queries": [{"query": q, "tier": 1} for q in body.get("queries", [])],
        "locations": [{"location": "São Paulo", "remote": False}],
        "location_accept": body.get("location_accept", []),
        "location_reject_non_remote": body.get("location_reject_non_remote", []),
        "country": "BRA",
        "glassdoor_location_map": {"São Paulo": "Sao Paulo"},
        "sites": body.get("sites", ["linkedin", "indeed"]),
        "defaults": body.get("defaults", {"results_per_site": 30, "hours_old": 168, "country_indeed": "brazil"}),
        "exclude_titles": body.get("exclude_titles", []),
    }

    SEARCH_CONFIG_PATH.write_text(
        yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return jsonify({"status": "saved"})


@bp.route("/api/jobs/apply", methods=["POST"])
def api_job_apply():
    """Apply to a single job immediately."""
    from applypilot.apply.engine import apply_to_job
    from applypilot.config import load_profile
    from applypilot.database import get_connection

    body = request.get_json(silent=True) or {}
    job_url = body.get("url", "")
    dry_run = body.get("dry_run", False)

    if not job_url:
        return jsonify({"error": "url required"}), 400

    conn = get_connection()
    row = conn.execute("SELECT * FROM jobs WHERE url = ?", (job_url,)).fetchone()
    if not row:
        return jsonify({"error": "job not found"}), 404

    profile = load_profile()
    try:
        result = apply_to_job(dict(row), profile, dry_run=dry_run)
    except Exception as e:
        result = {"status": "failed", "error": str(e)[:200]}

    return jsonify(result)
