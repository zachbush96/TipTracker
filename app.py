import os
import time
import logging
import click
from typing import Tuple, Literal

from flask import Flask, jsonify, render_template
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text, inspect, create_engine
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from sqlalchemy.pool import NullPool
from werkzeug.middleware.proxy_fix import ProxyFix

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# ---------- App ----------
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
CORS(app, resources={
    r"/api/integration-access(?:/.*)?": {"origins": []},
    r"/.*": {},
})

# ---------- Supabase configuration (used by frontend and auth blueprint) ----------
app.config["SUPABASE_URL"] = os.environ.get(
    "SUPABASE_URL", os.environ.get("SUPABASE_REST_URL", "").removesuffix("/").removesuffix("/rest/v1")
)
app.config["SUPABASE_ANON_KEY"] = os.environ.get("SUPABASE_ANON_KEY", "")

# ---------- Candidate Postgres URIs (always sslmode=require) ----------
def _psycopg2_uri(uri: str) -> str:
    # SQLAlchemy 2.1 defaults to psycopg3; this app installs psycopg2.
    for prefix in ("postgresql://", "postgres://"):
        if uri.startswith(prefix):
            return "postgresql+psycopg2://" + uri[len(prefix):]
    return uri


PRIMARY_DB_URI = _psycopg2_uri(os.environ.get("DATABASE_URL", ""))
FALLBACK_DB_URI = _psycopg2_uri(os.environ.get("DATABASE_URL_FALLBACK", ""))

# ---------- Tunables ----------
CONNECT_TIMEOUT = int(os.environ.get("DB_CONNECT_TIMEOUT", "6"))  # sec
PROBE_RETRIES = int(os.environ.get("DB_PROBE_RETRIES", "2"))      # total attempts per URI
RETRY_SLEEP = float(os.environ.get("DB_RETRY_SLEEP", "0.6"))      # sec between attempts
ALLOW_SQLITE_FALLBACK = os.environ.get("ALLOW_SQLITE_FALLBACK", "1") not in ("0", "false", "False")

# Base connect args for psycopg2
ENGINE_CONNECT_ARGS = {"connect_timeout": CONNECT_TIMEOUT, "sslmode": "require"}

def _safe_uri(uri: str) -> str:
    # Never log connection details, including query-string credentials.
    return "configured database"

def _probe_once(uri: str) -> bool:
    eng = None
    try:
        eng = create_engine(uri, connect_args=ENGINE_CONNECT_ARGS, pool_pre_ping=True)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except (OperationalError, SQLAlchemyError) as e:
        logger.warning("Database probe failed (%s)", type(e).__name__)
        return False
    finally:
        try:
            if eng is not None:
                eng.dispose()
        except Exception:
            pass

def _can_connect(uri: str, label: str) -> bool:
    logger.debug("Probing DB (%s): %s", label, _safe_uri(uri))
    for attempt in range(1, PROBE_RETRIES + 1):
        ok = _probe_once(uri)
        if ok:
            logger.info("DB probe OK (%s): %s", label, _safe_uri(uri))
            return True
        logger.warning("DB probe FAILED (%s) attempt %d/%d: %s",
                       label, attempt, PROBE_RETRIES, _safe_uri(uri))
        if attempt < PROBE_RETRIES:
            time.sleep(RETRY_SLEEP)
    return False

def _pick_working_db_uri() -> Tuple[str, Literal["primary","fallback","sqlite"]]:
    if PRIMARY_DB_URI.startswith("sqlite:"):
        return PRIMARY_DB_URI, "sqlite"
    # Try primary (5432)
    if PRIMARY_DB_URI and _can_connect(PRIMARY_DB_URI, "primary"):
        return PRIMARY_DB_URI, "primary"

    logger.warning("Primary failed; trying pooled fallback (6543)...")
    if FALLBACK_DB_URI and _can_connect(FALLBACK_DB_URI, "fallback"):
        return FALLBACK_DB_URI, "fallback"

    if ALLOW_SQLITE_FALLBACK:
        sqlite_uri = "sqlite:///local-fallback.db"
        logger.error("Both Postgres probes failed. Falling back to SQLite at %s", sqlite_uri)
        return sqlite_uri, "sqlite"

    # If we get here, we're configured to fail hard
    raise RuntimeError(
        "Unable to connect to Supabase Postgres using 5432 or 6543. "
        "Set ALLOW_SQLITE_FALLBACK=1 to boot with a local SQLite DB, "
        "or fix credentials/network/psycopg2."
    )

# ---------- Choose DB URI BEFORE registering Flask-SQLAlchemy ----------
WORKING_DB_URI, DB_MODE = _pick_working_db_uri()

# Engine options tuned per mode
engine_options = {
    "pool_pre_ping": True,
    "connect_args": ENGINE_CONNECT_ARGS,
}

# For PgBouncer on 6543: let PgBouncer do the pooling
if DB_MODE == "fallback":
    engine_options["poolclass"] = NullPool
    # Optional: keep statement_timeout low to fail fast
    engine_options["connect_args"] = {
        **ENGINE_CONNECT_ARGS,
        "options": "-c statement_timeout=5000",
    }

# Reasonable pool recycle for direct Postgres (5432)
if DB_MODE == "primary":
    engine_options["pool_recycle"] = 300

# SQLite: remove connect_args that psycopg2 would want
if DB_MODE == "sqlite":
    engine_options.pop("connect_args", None)

app.config["SQLALCHEMY_DATABASE_URI"] = WORKING_DB_URI
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_options
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

# ---------- App boot ----------
with app.app_context():
    # Import after db is configured
    import models  # noqa: E402
    import api     # noqa: E402
    import auth    # noqa: E402
    import integrations
    import integration_access
    app.config["INTEGRATIONS_DB_READY"] = DB_MODE != "sqlite" or PRIMARY_DB_URI.startswith("sqlite:")
    app.config["INTEGRATIONS_ENABLED"] = os.environ.get("INTEGRATIONS_ENABLED") == "1"
    app.config["INTEGRATIONS_CREATE_ENABLED"] = os.environ.get("INTEGRATIONS_CREATE_ENABLED") == "1"
    app.config["INTEGRATIONS_SELF_SERVICE_ENABLED"] = os.environ.get("INTEGRATIONS_SELF_SERVICE_ENABLED") == "1"
    app.register_blueprint(integrations.integration_bp, url_prefix="/api/integrations/v1")
    app.register_blueprint(integration_access.access_bp)

    app.register_blueprint(api.api_bp, url_prefix="/api")
    app.register_blueprint(auth.auth_bp, url_prefix="/auth")

    @app.route("/")
    def index():
        from datetime import datetime
        return render_template("index.html", now=datetime.now())

    @app.route("/terms")
    def terms():
        from datetime import datetime
        return render_template("terms.html", now=datetime.now())

    @app.route("/privacy")
    def privacy():
        from datetime import datetime
        return render_template("privacy.html", now=datetime.now())

    @app.route("/healthz")
    def healthz():
        # Try a lightweight ping
        ok = False
        err = None
        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            ok = True
        except Exception as e:
            err = "Database unavailable"
        return jsonify(
            status="ok" if ok else "degraded",
            db_mode=DB_MODE,
            db_uri=_safe_uri(WORKING_DB_URI),
            engine_opts=list(engine_options.keys()),
            error=None if ok else err,
        ), (200 if ok else 503)

    # Log basic DB info
    try:
        insp = inspect(db.engine)
        logger.info(
            "Connected schema: %s | Using URI: %s | Mode: %s",
            getattr(insp, "default_schema_name", "<unknown>"),
            _safe_uri(WORKING_DB_URI),
            DB_MODE,
        )
        # Touch the DB
        with db.engine.connect() as conn:
            ver = conn.execute(text("SELECT sqlite_version()" if DB_MODE == "sqlite" else "SELECT version()")).scalar()
            logger.info("DB version: %s", ver)
    except Exception as e:
        logger.warning("Engine init ping failed (%s)", type(e).__name__)

    @app.cli.command("init-dev-db")
    def init_dev_db():
        """Explicitly create browser tables in a configured local SQLite database."""
        if not PRIMARY_DB_URI.startswith("sqlite:") or db.engine.dialect.name != "sqlite":
            raise click.ClickException("Development initialization requires an explicit SQLite DATABASE_URL")
        # Production schema changes are never part of startup or this command.
        db.metadata.create_all(db.engine, tables=[models.User.__table__, models.TipEntry.__table__])
        click.echo("Development browser tables initialized.")
