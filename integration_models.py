"""Server-only integration state. No public credential-management routes."""
from app import db


class IntegrationGrant(db.Model):
    __tablename__ = 'integration_grants'
    id = db.Column(db.String(36), primary_key=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    user_id = db.Column(db.String, db.ForeignKey('users.id'), nullable=False)
    client_id = db.Column(db.String(100), nullable=False)
    audience = db.Column(db.String(100), nullable=False)
    scopes = db.Column(db.Text, nullable=False)
    expires_at = db.Column(db.BigInteger, nullable=False)
    revoked = db.Column(db.Boolean, nullable=False, default=False)


class TipPreview(db.Model):
    __tablename__ = 'integration_tip_previews'
    id = db.Column(db.String(36), primary_key=True)
    grant_id = db.Column(db.String(36), db.ForeignKey('integration_grants.id'), nullable=False)
    payload = db.Column(db.Text, nullable=False)
    expires_at = db.Column(db.BigInteger, nullable=False)
    # Unique consumption prevents reuse under a different idempotency key.
    consumed = db.Column(db.Boolean, nullable=False, default=False)


class TipReceipt(db.Model):
    __tablename__ = 'integration_tip_receipts'
    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey('users.id'), nullable=False)
    client_id = db.Column(db.String(100), nullable=False)
    key = db.Column(db.String(128), nullable=False)
    payload = db.Column(db.Text, nullable=False)
    tip_id = db.Column(db.Integer, db.ForeignKey('tip_entries.id', ondelete='SET NULL'), nullable=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'client_id', 'key'),)
