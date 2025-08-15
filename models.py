from app import db
from datetime import datetime, timezone
from sqlalchemy import func

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.String, primary_key=True)  # Supabase UUID
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='server')  # 'server' or 'manager'
    restaurant_id = db.Column(db.String, nullable=True)  # For multi-tenant support
    created_at = db.Column(db.DateTime(timezone=True), default=func.now())
    updated_at = db.Column(db.DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    # Relationships
    tip_entries = db.relationship('TipEntry', backref='user', lazy=True)

class TipEntry(db.Model):
    __tablename__ = 'tip_entries'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey('users.id'), nullable=False)
    cash_tips = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    card_tips = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    hours_worked = db.Column(db.Numeric(4, 2), nullable=False)
    section = db.Column(db.String(50), nullable=True)
    sales_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    work_date = db.Column(db.Date, nullable=False)
    weekday = db.Column(db.Integer, nullable=False)  # 0=Monday, 6=Sunday
    total_tips = db.Column(db.Numeric(10, 2), nullable=False)  # Computed field
    tips_per_hour = db.Column(db.Numeric(8, 2), nullable=False)  # Computed field
    tip_percentage = db.Column(db.Numeric(5, 2), nullable=False)  # Computed field
    comments = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=func.now())
    updated_at = db.Column(db.DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    def __init__(self, **kwargs):
        super(TipEntry, self).__init__(**kwargs)
        # Compute derived fields
        self.total_tips = float(self.cash_tips or 0) + float(self.card_tips or 0)
        if self.hours_worked and self.hours_worked > 0:
            self.tips_per_hour = round(self.total_tips / float(self.hours_worked), 2)
        else:
            self.tips_per_hour = 0
        if self.sales_amount and float(self.sales_amount) > 0:
            self.tip_percentage = round(self.total_tips / float(self.sales_amount) * 100, 2)
        else:
            self.tip_percentage = 0

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'cash_tips': float(self.cash_tips),
            'card_tips': float(self.card_tips),
            'hours_worked': float(self.hours_worked),
            'section': self.section,
            'sales_amount': float(self.sales_amount),
            'work_date': self.work_date.isoformat(),
            'weekday': self.weekday,
            'total_tips': float(self.total_tips),
            'tips_per_hour': float(self.tips_per_hour),
            'tip_percentage': float(self.tip_percentage),
            'comments': self.comments,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
