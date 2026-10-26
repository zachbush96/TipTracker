"""Opt-in own-user API with reviewed previews and transactional retry receipts."""
import hashlib
import json
import re
import time
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.exceptions import HTTPException

from app import db
from integration_models import IntegrationGrant, TipPreview, TipReceipt
from models import TipEntry, User
from tip_domain import calculate_totals

integration_bp = Blueprint('integrations', __name__)
AUDIENCE = 'tiptracker-integrations-v1'
FIELDS = {'work_date', 'section', 'cash_tips', 'card_tips', 'tip_out',
          'sales_amount', 'hours_worked', 'comments'}
MONEY = ('cash_tips', 'card_tips', 'sales_amount', 'tip_out')


class InvalidInput(ValueError):
    pass


def fail(message, status=400):
    return jsonify(error=message, request_id=g.request_id), status


@integration_bp.before_request
def initialize_request():
    g.request_id = str(uuid.uuid4())
    if not current_app.config.get('INTEGRATIONS_ENABLED', False):
        return fail('Integration API is disabled', 404)
    if not current_app.config.get('INTEGRATIONS_DB_READY', False):
        return fail('Integration access is unavailable on an automatic database fallback', 503)
    # A small body limit applies without changing browser uploads.
    request.max_content_length = 16384


@integration_bp.after_request
def audit(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Request-ID'] = g.request_id
    grant = getattr(g, 'grant', None)
    current_app.logger.info('integration_request request=%s actor=%s client=%s entry=%s outcome=%s',
                            g.request_id, grant.user_id if grant else '-',
                            grant.client_id if grant else '-', getattr(g, 'entry_id', '-'),
                            response.status_code)
    return response


@integration_bp.errorhandler(InvalidInput)
def invalid_input(error):
    return fail(str(error))


@integration_bp.errorhandler(HTTPException)
def http_error(error):
    return fail(error.name, error.code)


@integration_bp.errorhandler(SQLAlchemyError)
def database_error(error):
    db.session.rollback()
    return fail('Database operation failed', 503)


def scoped(scope):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            authorization = request.headers.get('Authorization', '')
            if not authorization.startswith('Bearer ') or len(authorization) > 1024:
                return fail('Integration credential required', 401)
            token = authorization[7:]
            grant = IntegrationGrant.query.filter_by(
                token_hash=hashlib.sha256(token.encode()).hexdigest()).first()
            client_id = request.headers.get('X-Integration-Client')
            if (not grant or grant.revoked or grant.expires_at <= int(time.time())
                    or grant.audience != AUDIENCE or grant.client_id != client_id
                    or db.session.get(User, grant.user_id) is None):
                return fail('Invalid integration credential', 401)
            g.grant = grant
            if scope not in grant.scopes.split():
                return fail('Insufficient scope', 403)
            return fn(*args, **kwargs)
        return wrapped
    return decorate


def strict_object():
    if not request.is_json:
        raise InvalidInput('Content-Type must be application/json')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InvalidInput('Duplicate JSON field')
            result[key] = value
        return result
    try:
        value = json.loads(request.get_data(), parse_float=Decimal,
                           parse_constant=lambda value: (_ for _ in ()).throw(InvalidInput('Non-finite number')),
                           object_pairs_hook=pairs)
    except (ValueError, UnicodeError):
        raise InvalidInput('Invalid JSON object') from None
    if type(value) is not dict:
        raise InvalidInput('A JSON object is required')
    return value


def decimal_field(value, field, maximum):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise InvalidInput(f'{field} requires an explicit decimal value')
    if len(str(value)) > 40:
        raise InvalidInput(f'{field} is too large')
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > maximum:
            raise InvalidInput(f'{field} is outside its permitted range')
        if number.as_tuple().exponent < -2:
            raise InvalidInput(f'{field} permits at most two decimal places')
        return number
    except InvalidOperation:
        raise InvalidInput(f'{field} is invalid') from None


def parse_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise InvalidInput('Use an explicit YYYY-MM-DD work date')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise InvalidInput('Invalid work date') from None


def normalize(data):
    if set(data) - FIELDS:
        raise InvalidInput('Unexpected fields: ' + ', '.join(sorted(set(data) - FIELDS)))
    missing = sorted(FIELDS - set(data))
    unresolved = missing + [key for key in MONEY + ('hours_worked', 'work_date')
                            if key in data and data[key] is None]
    if unresolved:
        return None, sorted(set(unresolved)), []
    work_date = parse_date(data['work_date'])
    today = datetime.now(ZoneInfo('America/New_York')).date()
    if work_date > today:
        raise InvalidInput('Work date cannot be in the future')
    numbers = {key: decimal_field(data[key], key, Decimal('99999999.99')) for key in MONEY}
    numbers['hours_worked'] = decimal_field(data['hours_worked'], 'hours_worked', Decimal('24'))
    if numbers['hours_worked'] <= 0:
        raise InvalidInput('hours_worked must exceed zero')
    result = {'work_date': work_date.isoformat()}
    for key, limit in [('section', 50), ('comments', 500)]:
        value = data[key]
        if value is not None and not isinstance(value, str):
            raise InvalidInput(f'{key} must be text or null')
        value = value.strip() if value else None
        if key == 'section' and value:
            value = value.lower()
        if value and len(value) > limit:
            raise InvalidInput(f'{key} exceeds {limit} characters')
        result[key] = value
    totals = calculate_totals(*(numbers[k] for k in ('cash_tips', 'card_tips', 'hours_worked', 'sales_amount', 'tip_out')))
    for key, maximum in [('total_tips', '99999999.99'), ('net_tips', '99999999.99'), ('tips_per_hour', '999999.99'), ('tip_percentage', '999.99')]:
        if abs(totals[key]) > Decimal(maximum):
            raise InvalidInput(f'{key} exceeds database precision')
    result.update({key: format(value, '.2f') for key, value in numbers.items()})
    return result, [], []


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(',', ':'))


def own_tips():
    return TipEntry.query.filter_by(user_id=g.grant.user_id)


def serialize(tip):
    result = {key: format(getattr(tip, key), '.2f') for key in
              MONEY + ('hours_worked', 'total_tips', 'net_tips', 'tips_per_hour', 'tip_percentage')}
    result.update(id=tip.id, work_date=tip.work_date.isoformat(), section=tip.section,
                  comments=tip.comments)
    return result


@integration_bp.get('/tips')
@scoped('tips:read')
def list_tips():
    if set(request.args) - {'limit', 'offset', 'start_date', 'end_date'}:
        raise InvalidInput('Unsupported query parameter')
    try:
        limit = int(request.args.get('limit', '25'))
        offset = int(request.args.get('offset', '0'))
    except ValueError:
        raise InvalidInput('Invalid pagination') from None
    if not 1 <= limit <= 100 or not 0 <= offset <= 100000:
        raise InvalidInput('Pagination is outside its permitted range')
    today = datetime.now(ZoneInfo('America/New_York')).date()
    start = parse_date(request.args['start_date']) if 'start_date' in request.args else today - timedelta(days=30)
    end = parse_date(request.args['end_date']) if 'end_date' in request.args else today
    if start > end:
        raise InvalidInput('start_date must not exceed end_date')
    rows = own_tips().filter(TipEntry.work_date.between(start, end)).order_by(
        TipEntry.work_date.desc(), TipEntry.id.desc()).offset(offset).limit(limit + 1).all()
    return jsonify(tips=[serialize(t) for t in rows[:limit]],
                   next_offset=offset + limit if len(rows) > limit else None)


@integration_bp.get('/tips/<int:tip_id>')
@scoped('tips:read')
def get_tip(tip_id):
    tip = own_tips().filter_by(id=tip_id).first()
    if not tip:
        return fail('Entry not found', 404)
    g.entry_id = tip.id
    return jsonify(tip_entry=serialize(tip))


@integration_bp.get('/sections')
@scoped('tips:read')
def sections():
    rows = db.session.query(TipEntry.section).filter(
        TipEntry.user_id == g.grant.user_id, TipEntry.section.isnot(None)).distinct().order_by(
            TipEntry.section).limit(100).all()
    return jsonify(sections=[row[0] for row in rows if row[0]])


@integration_bp.post('/tip-previews')
@scoped('tips:create')
def preview():
    payload, unresolved, warnings = normalize(strict_object())
    if unresolved:
        return jsonify(ready=False, unresolved_fields=unresolved, warnings=warnings, preview_id=None), 422
    duplicates = own_tips().filter_by(work_date=parse_date(payload['work_date'])).order_by(TipEntry.id).limit(20).all()
    record = TipPreview(id=str(uuid.uuid4()), grant_id=g.grant.id,
                        payload=canonical(payload), expires_at=int(time.time()) + 600)
    db.session.add(record)
    db.session.commit()
    totals = calculate_totals(*(payload[k] for k in ('cash_tips', 'card_tips', 'hours_worked', 'sales_amount', 'tip_out')))
    return jsonify(ready=True, preview_id=record.id, expires_at=record.expires_at,
                   entry=payload, totals={k: format(v, '.2f') for k, v in totals.items()},
                   possible_duplicates=[serialize(t) for t in duplicates],
                   warnings=['Resolve same-day entries with the user before approval.'] if duplicates else [],
                   consent_required=True)


def receipt_response(receipt, payload):
    if receipt.payload != payload:
        return fail('Idempotency key already used for another payload', 409)
    tip = own_tips().filter_by(id=receipt.tip_id).first()
    if not tip:
        return fail('Original entry no longer exists', 409)
    g.entry_id = tip.id
    return jsonify(tip_entry=serialize(tip), replayed=True), 200


@integration_bp.post('/tips')
@scoped('tips:create')
def create_tip():
    if not current_app.config.get('INTEGRATIONS_CREATE_ENABLED', False):
        return fail('Integration creation is disabled pending deployment review', 403)
    data = strict_object()
    if set(data) != {'preview_id', 'entry'} or type(data['entry']) is not dict:
        raise InvalidInput('Supply only preview_id and the exact approved entry')
    if not isinstance(data['preview_id'], str) or len(data['preview_id']) > 36:
        raise InvalidInput('Invalid preview_id')
    key = request.headers.get('Idempotency-Key', '')
    if not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', key):
        raise InvalidInput('Supply an Idempotency-Key of 1–128 permitted characters')
    payload, unresolved, _ = normalize(data['entry'])
    if unresolved:
        raise InvalidInput('Resolve all fields before creation')
    payload_text = canonical(payload)
    # Require the normalized preview, not an equivalent unreviewed representation.
    if data['entry'] != payload:
        raise InvalidInput('Entry must exactly match the normalized preview')
    receipt_query = dict(user_id=g.grant.user_id, client_id=g.grant.client_id, key=key)
    receipt = TipReceipt.query.filter_by(**receipt_query).first()
    if receipt:
        return receipt_response(receipt, payload_text)
    record = TipPreview.query.filter_by(id=data['preview_id'], grant_id=g.grant.id).first()
    if not record or record.payload != payload_text:
        return fail('Preview does not match this owner and payload', 409)
    # Conditional UPDATE serializes competing consumers on PostgreSQL and SQLite.
    consumed = TipPreview.query.filter_by(id=record.id, grant_id=g.grant.id, consumed=False).filter(
        TipPreview.expires_at > int(time.time())).update({'consumed': True}, synchronize_session=False)
    if not consumed:
        db.session.rollback()
        receipt = TipReceipt.query.filter_by(**receipt_query).first()
        if receipt:
            return receipt_response(receipt, payload_text)
        return fail('Preview expired or already consumed. Request a new preview.', 409)
    fields = dict(payload)
    fields['work_date'] = parse_date(fields['work_date'])
    for field in MONEY + ('hours_worked',):
        fields[field] = Decimal(fields[field])
    tip = TipEntry(user_id=g.grant.user_id, weekday=fields['work_date'].weekday(), **fields)
    try:
        db.session.add(tip)
        db.session.flush()
        db.session.add(TipReceipt(id=str(uuid.uuid4()), tip_id=tip.id, payload=payload_text, **receipt_query))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        receipt = TipReceipt.query.filter_by(**receipt_query).first()
        if receipt:
            return receipt_response(receipt, payload_text)
        return fail('Concurrent request conflict. Retry the same key.', 409)
    g.entry_id = tip.id
    return jsonify(tip_entry=serialize(tip), replayed=False), 201
