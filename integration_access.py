"""Same-origin, verified-user consent for short-lived own-history read grants."""
import hashlib
import re
import secrets
import time
import uuid
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, render_template, request, session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
try:  # Production lockfile uses the earlier GoTrue package name.
    from supabase_auth.errors import AuthApiError
except ImportError:
    from gotrue.errors import AuthApiError
from werkzeug.exceptions import HTTPException

from app import db
from auth import get_supabase_client
from integration_models import IntegrationGrant
from integrations import AUDIENCE, InvalidInput, strict_object
from models import User

access_bp = Blueprint('integration_access', __name__)
CONSENT = 'read-only-own-history-v1'
SESSION_KEY = 'integration_access_consent'


def error(message, status):
    return jsonify(error=message, request_id=g.request_id), status


@access_bp.before_request
def access_gate():
    g.request_id = str(uuid.uuid4())
    request.max_content_length = 4096
    if not (current_app.config.get('INTEGRATIONS_ENABLED')
            and current_app.config.get('INTEGRATIONS_SELF_SERVICE_ENABLED')):
        return error('Integration connections are not enabled', 404)
    if not current_app.config.get('INTEGRATIONS_DB_READY'):
        return error('Integration connections are unavailable', 503)
    # A missing/default session secret must never protect credential management.
    key = current_app.secret_key
    if (not isinstance(key, (str, bytes)) or len(key) < 32
            or key in ('dev-secret-key-change-in-production',
                       'your-super-secret-session-key-change-this-in-production',
                       b'dev-secret-key-change-in-production',
                       b'your-super-secret-session-key-change-this-in-production')):
        return error('Integration connections are unavailable', 503)


@access_bp.after_request
def private_response(response):
    response.headers.update({
        'Cache-Control': 'no-store', 'Pragma': 'no-cache',
        'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY', 'X-Request-ID': g.request_id,
        'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    })
    # Deliberately exclude session tokens, grant tokens/hashes, client input and payloads.
    current_app.logger.info('integration_access request=%s actor=%s grant=%s outcome=%s',
                            g.request_id, getattr(g, 'access_subject', '-'),
                            getattr(g, 'access_grant_id', '-'), response.status_code)
    return response


@access_bp.errorhandler(SQLAlchemyError)
def database_error(exception):
    db.session.rollback()
    return error('Connection storage is unavailable. No credential can be recovered here.', 503)


@access_bp.errorhandler(InvalidInput)
def invalid_input(exception):
    return error(str(exception), 400)


@access_bp.errorhandler(HTTPException)
def http_error(exception):
    return error(exception.name, exception.code)


def verified_user(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        identity = session.get('user')
        token = identity.get('access_token') if isinstance(identity, dict) else None
        if not isinstance(token, str) or not token or len(token) > 16384:
            return error('Sign in to Tip Tracker again to manage connections', 401)
        try:
            supabase = get_supabase_client()
            if supabase is None:
                return error('Sign-in verification is unavailable', 503)
            verified = supabase.auth.get_user(token)
            subject = str(verified.user.id) if verified and verified.user else None
        except AuthApiError:
            return error('Sign in to Tip Tracker again to manage connections', 401)
        except Exception:
            return error('Sign-in verification is unavailable', 503)
        if not subject:
            return error('Sign in to Tip Tracker again to manage connections', 401)
        # Never derive authorization from the cookie's id, email, name or role.
        profile = db.session.get(User, subject)
        if profile is None:
            return error('An existing Tip Tracker profile is required', 403)
        g.access_subject = subject
        g.access_profile = profile
        return fn(*args, **kwargs)
    return wrapped


def check_consent_request():
    # Custom CSRF header + exact origin; no credentialed cross-origin management.
    if request.headers.get('Origin') != request.host_url.rstrip('/'):
        return error('Use the Tip Tracker connection page for this action', 403)
    if request.headers.get('Sec-Fetch-Site') not in (None, 'same-origin'):
        return error('Use the Tip Tracker connection page for this action', 403)
    record = session.get(SESSION_KEY)
    token = request.headers.get('X-CSRF-Token', '')
    if (not isinstance(record, dict) or record.get('owner') != g.access_subject
            or not isinstance(record.get('token'), str)
            or type(record.get('expires_at')) is not int
            or record['expires_at'] <= int(time.time())
            or len(token) > 128
            or not secrets.compare_digest(token.encode(), record['token'].encode())):
        return error('Refresh connections before confirming this action', 403)
    return None


@access_bp.get('/integrations')
def access_page():
    return render_template('integration_access.html')


@access_bp.get('/api/integration-access')
@verified_user
def connections():
    if set(request.args) - {'offset'}:
        return error('Unsupported query parameter', 400)
    try:
        offset = int(request.args.get('offset', '0'))
    except ValueError:
        return error('Invalid connection offset', 400)
    if not 0 <= offset <= 100000:
        return error('Invalid connection offset', 400)
    records = IntegrationGrant.query.filter_by(user_id=g.access_subject).order_by(
        IntegrationGrant.expires_at.desc(), IntegrationGrant.id.desc()).offset(offset).limit(101).all()
    consent = dict(owner=g.access_subject, token=secrets.token_urlsafe(32),
                   issuance_id=str(uuid.uuid4()), expires_at=int(time.time()) + 600)
    session[SESSION_KEY] = consent
    return jsonify(account=g.access_profile.email, csrf_token=consent['token'],
                   issuance_id=consent['issuance_id'], consent=CONSENT,
                   next_offset=offset + 100 if len(records) > 100 else None,
                   connections=[dict(id=r.id, client_id=r.client_id, scopes=r.scopes.split(),
                                     expires_at=r.expires_at, revoked=r.revoked) for r in records[:100]])


@access_bp.post('/api/integration-access/grants')
@verified_user
def issue_read_grant():
    failed = check_consent_request()
    if failed:
        return failed
    data = strict_object()
    if set(data) != {'client_id', 'expires_in_hours', 'consent', 'issuance_id'}:
        return error('Confirm only the client, expiry and read-only consent shown', 400)
    client_id = data['client_id']
    if not isinstance(client_id, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._:-]{0,63}', client_id):
        return error('Client ID must use 1–64 lowercase letters, digits, dots, underscores, colons or hyphens', 400)
    hours = data['expires_in_hours']
    if type(hours) is not int or hours not in (1, 24):
        return error('Choose an expiry of 1 or 24 hours', 400)
    consent = session[SESSION_KEY]
    if data['consent'] != CONSENT or data['issuance_id'] != consent['issuance_id']:
        return error('Refresh connections and explicitly confirm read-only access', 403)
    # One server-issued ID per confirmation prevents retry/double-click duplication.
    if db.session.get(IntegrationGrant, consent['issuance_id']) is not None:
        return error('This request was already used. Review connections; tokens cannot be shown again.', 409)
    token = 'tt_read_' + secrets.token_urlsafe(32)
    grant = IntegrationGrant(id=consent['issuance_id'], user_id=g.access_subject,
        token_hash=hashlib.sha256(token.encode()).hexdigest(), client_id=client_id,
        audience=AUDIENCE, scopes='tips:read', expires_at=int(time.time()) + hours * 3600,
        revoked=False)
    try:
        db.session.add(grant)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error('This request was already used. Review connections; tokens cannot be shown again.', 409)
    g.access_grant_id = grant.id
    return jsonify(id=grant.id, token=token, client_id=grant.client_id,
                   scopes=['tips:read'], expires_at=grant.expires_at), 201


@access_bp.post('/api/integration-access/grants/<uuid:grant_id>/revoke')
@verified_user
def revoke_grant(grant_id):
    failed = check_consent_request()
    if failed:
        return failed
    data = strict_object()
    if set(data) != {'revoke'} or data['revoke'] is not True:
        return error('Explicitly confirm revocation', 400)
    grant = IntegrationGrant.query.filter_by(id=str(grant_id), user_id=g.access_subject).first()
    if grant is None:
        return error('Connection not found', 404)
    grant.revoked = True
    db.session.commit()
    g.access_grant_id = grant.id
    return jsonify(revoked=True)
