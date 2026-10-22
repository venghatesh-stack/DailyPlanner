import os
from flask import Flask, session, request, jsonify, render_template, send_from_directory
from flask_login import current_user
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import HTTPException
from logger import setup_logger
from settings import config_map
from extensions import login_manager, csrf, limiter

logger = setup_logger()


def create_app():
    app = Flask(__name__)

    # ── Config ──────────────────────────────────────────
    env = os.environ.get("FLASK_ENV", "production")
    app.config.from_object(config_map.get(env, config_map["production"]))

    # Static files (CSS, JS, deity portraits, icons) get a 30-day
    # browser-cache so phones don't re-download them on every visit.
    # We cache-bust by adding ?v=<deploy id> to URLs that change; static
    # assets here are content-stable so a long max-age is safe and
    # dramatically reduces /prayer's bandwidth bill on repeat visits.
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 60 * 60 * 24 * 30  # 30 days

    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1
    )

    # ── Extensions ──────────────────────────────────────
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        from models.user import User
        return User.get(user_id)

    # ── Session bridge ──────────────────────────────────
    # Keeps session["user_id"] populated for all existing routes
    @app.before_request
    def sync_session_user_id():
        if current_user.is_authenticated:
            session["user_id"] = current_user.get_id()
            session["authenticated"] = True

    # ── Security headers ────────────────────────────────
    from middleware.security import apply_security_headers
    apply_security_headers(app)

    # ── Blueprints ──────────────────────────────────────
    from routes.auth import auth_bp
    from routes.planner import planner_bp
    from routes.todo import todo_bp
    from routes.projects import projects_bp
    from routes.health import health_bp
    from routes.habits import habits_bp
    from routes.references import references_bp
    from routes.ai import ai_bp
    from routes.events import events_bp
    from routes.timeline import timeline_bp
    from routes.notes import notes_bp
    from routes.system import system_bp
    from routes.inbox import inbox_bp
    from routes.refcards import refcards_bp
    from routes.portfolio import portfolio_bp
    from routes.goals import goals_bp
    from routes.reports import reports_bp
    from routes.settings import settings_bp
    from routes.announcer import announcer_bp
    from routes.archive import archive_bp
    from routes.checklist import checklist_bp
    from routes.push import push_bp
    from routes.prayer import prayer_bp
    from routes.relationships import relationships_bp
    from routes.focus_log import focus_log_bp
    from routes.photos import photos_bp
    from routes.prescriptions import prescriptions_bp
    from routes.quotes import quotes_bp
    from routes.mythology import mythology_bp
    from routes.grocery import grocery_bp
    from routes.color_notes import color_notes_bp
    from routes.travel_reads import travel_reads_bp
    from routes.shared import shared_bp
    from routes.tasks_bucket import tasks_bucket_bp
    from routes.quick_bucket import quick_bucket_bp
    from routes.day_board import day_board_bp
    from routes.backlog import backlog_bp
    from routes.day import day_bp
    from routes.java_prep import java_prep_bp
    from routes.sql_prep import sql_prep_bp
    from routes.bedtime_stories import bedtime_stories_bp, user_allowed as _bedtime_allowed
    from routes.study import study_bp
    from routes.meetings import meetings_bp
    from routes.programs import programs_bp
    from routes.knowledgebase import knowledgebase_bp
    from routes.chat import chat_bp, user_allowed as _chat_allowed
    from routes.page_hints import page_hints_bp
    from routes.family_tasks import family_tasks_bp
    from routes.admin import admin_bp
    from routes.expenses import expenses_bp
    from routes.investments import investments_bp
    from routes.interview_prep import interview_prep_bp

    app.register_blueprint(announcer_bp)
    app.register_blueprint(archive_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(planner_bp)
    app.register_blueprint(todo_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(habits_bp)
    app.register_blueprint(references_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(timeline_bp)
    app.register_blueprint(notes_bp)
    app.register_blueprint(inbox_bp)
    app.register_blueprint(refcards_bp)
    app.register_blueprint(portfolio_bp)
    app.register_blueprint(goals_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(checklist_bp)
    app.register_blueprint(push_bp)
    app.register_blueprint(prayer_bp)
    app.register_blueprint(relationships_bp)
    app.register_blueprint(focus_log_bp)
    app.register_blueprint(photos_bp)
    app.register_blueprint(prescriptions_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(mythology_bp)
    app.register_blueprint(grocery_bp)
    app.register_blueprint(color_notes_bp)
    app.register_blueprint(travel_reads_bp)
    app.register_blueprint(shared_bp)
    app.register_blueprint(tasks_bucket_bp)
    app.register_blueprint(quick_bucket_bp)
    app.register_blueprint(day_board_bp)
    app.register_blueprint(backlog_bp)
    app.register_blueprint(day_bp)
    # Interview Prep (all its pages and APIs, plus Java and SQL) is only for
    # the accounts in utils/prep_access.py; each blueprint guards itself.
    from utils.prep_access import prep_allowed as _prep_allowed
    app.register_blueprint(java_prep_bp)
    app.register_blueprint(sql_prep_bp)
    app.register_blueprint(bedtime_stories_bp)
    app.register_blueprint(study_bp)
    app.register_blueprint(meetings_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(knowledgebase_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(page_hints_bp)
    app.register_blueprint(family_tasks_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(investments_bp)
    app.register_blueprint(interview_prep_bp)

    # Gzip text responses on the way out. Registered after the blueprints so
    # it wraps every one of them; see utils/compression.py for the rules.
    from utils.compression import init_app as _init_compression
    _init_compression(app)

    # Expose the bedtime-stories allowlist flag to every template so the
    # nav can hide the link from non-allowed users without each template
    # importing the helper.
    @app.context_processor
    def _inject_bedtime_flag():
        try:
            return {"bedtime_stories_enabled": _bedtime_allowed()}
        except Exception:
            return {"bedtime_stories_enabled": False}

    # Same pattern for chat — hides the nav link from non-allowlisted
    # users so the feature is invisible to them. Env-var driven; see
    # CHAT_USER_EMAILS in routes/chat.py.
    @app.context_processor
    def _inject_chat_flag():
        try:
            return {"chat_enabled": _chat_allowed()}
        except Exception:
            return {"chat_enabled": False}

    # Interview Prep flag — hides the whole prep group from other users.
    @app.context_processor
    def _inject_prep_flag():
        try:
            return {"prep_enabled": _prep_allowed()}
        except Exception:
            return {"prep_enabled": False}

    # Admin flag — shows the "Usage & Backup" nav link only to admins.
    @app.context_processor
    def _inject_admin_flag():
        try:
            from flask_login import current_user
            from routes.admin import _admin_emails
            email = (getattr(current_user, "email", "") or "").lower()
            return {"admin_enabled": bool(email) and email in _admin_emails()}
        except Exception:
            return {"admin_enabled": False}

    # ── Exempt JSON API blueprints from CSRF ────────────
    # These use session auth + @login_required, not form tokens
    csrf.exempt(events_bp)
    csrf.exempt(page_hints_bp)
    csrf.exempt(habits_bp)
    csrf.exempt(health_bp)
    csrf.exempt(ai_bp)
    csrf.exempt(inbox_bp)
    csrf.exempt(timeline_bp)
    csrf.exempt(projects_bp)
    csrf.exempt(todo_bp)
    csrf.exempt(planner_bp)
    csrf.exempt(notes_bp)
    csrf.exempt(refcards_bp)
    csrf.exempt(portfolio_bp)
    csrf.exempt(references_bp)
    csrf.exempt(goals_bp)
    csrf.exempt(reports_bp)
    csrf.exempt(settings_bp)
    csrf.exempt(checklist_bp)
    csrf.exempt(push_bp)
    csrf.exempt(focus_log_bp)
    csrf.exempt(prayer_bp)
    csrf.exempt(photos_bp)
    csrf.exempt(quotes_bp)
    csrf.exempt(mythology_bp)
    csrf.exempt(grocery_bp)
    csrf.exempt(color_notes_bp)
    csrf.exempt(travel_reads_bp)
    csrf.exempt(shared_bp)
    csrf.exempt(tasks_bucket_bp)
    csrf.exempt(quick_bucket_bp)
    csrf.exempt(bedtime_stories_bp)
    csrf.exempt(study_bp)
    csrf.exempt(meetings_bp)
    csrf.exempt(programs_bp)
    csrf.exempt(knowledgebase_bp)
    csrf.exempt(chat_bp)
    csrf.exempt(family_tasks_bp)
    csrf.exempt(admin_bp)
    csrf.exempt(expenses_bp)

    # ── PWA: serve SW + manifest from the site root so the service
    # worker's scope is "/" (otherwise it's confined to /static/...).
    #
    # These two files are cache-busted explicitly: SEND_FILE_MAX_AGE_DEFAULT
    # is 30 days (great for icons and CSS), but a stale manifest means
    # an installed PWA never picks up start_url / launch_handler changes,
    # and a stale service-worker can serve out-of-date HTML for weeks.
    # Tell the browser to revalidate every load.
    def _no_cache(resp):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    @app.route("/service-worker.js")
    def _service_worker():
        resp = send_from_directory(
            app.static_folder, "service-worker.js",
            mimetype="application/javascript",
        )
        return _no_cache(resp)

    @app.route("/manifest.json")
    def _manifest():
        resp = send_from_directory(
            app.static_folder, "manifest.json",
            mimetype="application/manifest+json",
        )
        return _no_cache(resp)

    # ── Start the push reminder scheduler (idempotent) ──
    try:
        from services import push_scheduler
        push_scheduler.start(app)
    except Exception:
        logger.exception("Could not start push scheduler")

    # ── OAuth dev override ──────────────────────────────
    if env == "development":
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    # ── Error handlers ──────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "error": "Not found"}), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(429)
    def rate_limited(e):
        from flask_limiter.util import get_remote_address
        logger.warning("Rate limit exceeded for IP=%s path=%s",
                       get_remote_address(), request.path)
        return jsonify({"status": "error", "error": "Too many requests. Please slow down."}), 429

    @app.errorhandler(500)
    def server_error(e):
        logger.exception("Unhandled server error")
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "error": "Internal server error"}), 500
        return render_template("errors/500.html"), 500

    @app.errorhandler(Exception)
    def handle_exception(e):
        # An HTTP error raised on purpose (405 wrong method, 400 bad JSON or
        # a missing CSRF token, 403, 413 ...) also lands here, because this
        # handler catches everything. It is the request's fault, not a crash:
        # answer with its own code and leave it out of the exception log.
        # Before this, every one of them went out as a 500.
        if isinstance(e, HTTPException):
            if request.path.startswith("/api/"):
                return jsonify({"status": "error", "error": e.description or e.name}), e.code
            return e
        # logger.exception captures the traceback through the logger,
        # avoiding stack-trace leakage to stdout in production.
        logger.exception("Unhandled exception: %s", str(e))
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "error": "Internal server error"}), 500
        raise e

    return app
