from flask import Blueprint, request, jsonify
from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import joinedload
from app import db
from models import User, TipEntry
from auth import require_auth, get_current_user
from demo_data import get_demo_data

api_bp = Blueprint('api', __name__)

def validate_tip_entry(data):
    """Validate tip entry data"""
    errors = []
    
    # Validate cash_tips
    cash_tips = data.get('cash_tips', 0)
    try:
        cash_tips = float(cash_tips)
        if cash_tips < 0:
            errors.append('Cash tips cannot be negative')
    except (ValueError, TypeError):
        errors.append('Cash tips must be a valid number')
    
    # Validate card_tips
    card_tips = data.get('card_tips', 0)
    try:
        card_tips = float(card_tips)
        if card_tips < 0:
            errors.append('Card tips cannot be negative')
    except (ValueError, TypeError):
        errors.append('Card tips must be a valid number')
    
    # Validate hours_worked
    hours_worked = data.get('hours_worked')
    try:
        hours_worked = float(hours_worked)
        if hours_worked <= 0:
            errors.append('Hours worked must be greater than 0')
        if hours_worked > 24:
            errors.append('Hours worked cannot exceed 24')
    except (ValueError, TypeError):
        errors.append('Hours worked must be a valid number')

    # Comments (optional)
    comments = data.get('comments', '')
    if comments is not None:
        comments = str(comments).strip()
        if len(comments) > 500:
            errors.append('Comments cannot exceed 500 characters')

    return errors, {
        'cash_tips': round(cash_tips, 2),
        'card_tips': round(card_tips, 2),
        'hours_worked': round(hours_worked, 2),
        'comments': comments
    }

@api_bp.route('/tips', methods=['POST'])
@require_auth
def create_tip_entry():
    """Create a new tip entry"""
    try:
        data = request.get_json()
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'Authentication required'}), 401
        
        # Validate input
        errors, validated_data = validate_tip_entry(data)
        if errors:
            return jsonify({'errors': errors}), 400
        
        # Ensure user exists in database
        user = User.query.filter_by(id=current_user['id']).first()
        if not user:
            # Create user if doesn't exist
            user = User()
            user.id = current_user['id']
            user.email = current_user['email']
            user.name = current_user['name']
            user.role = 'server'  # Default role
            db.session.add(user)
            db.session.commit()
        
        # Get work date (server-side)
        work_date = date.today()
        weekday = work_date.weekday()  # 0=Monday, 6=Sunday
        
        # Create tip entry
        tip_entry = TipEntry(
            user_id=current_user['id'],
            cash_tips=Decimal(str(validated_data['cash_tips'])),
            card_tips=Decimal(str(validated_data['card_tips'])),
            hours_worked=Decimal(str(validated_data['hours_worked'])),
            work_date=work_date,
            weekday=weekday,
            comments=validated_data.get('comments') or None
        )
        
        db.session.add(tip_entry)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'tip_entry': tip_entry.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@api_bp.route('/tips', methods=['GET'])
@require_auth
def get_tips():
    """Get tip entries with filtering"""
    try:
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'Authentication required'}), 401
        
        demo_mode = request.args.get('demo', 'false').lower() == 'true'
        
        if demo_mode:
            return jsonify(get_demo_data('tips'))
        
        # Date filtering
        days = request.args.get('days', '30')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Build query
        query = TipEntry.query.options(joinedload(TipEntry.user))
        
        # Role-based filtering
        user = User.query.filter_by(id=current_user['id']).first()
        if not user or user.role != 'manager':
            query = query.filter_by(user_id=current_user['id'])
        
        # Date filtering
        if start_date and end_date:
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
                query = query.filter(and_(
                    TipEntry.work_date >= start_date,
                    TipEntry.work_date <= end_date
                ))
            except ValueError:
                return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
        else:
            try:
                days_int = int(days)
                start_date = date.today() - timedelta(days=days_int)
                query = query.filter(TipEntry.work_date >= start_date)
            except ValueError:
                return jsonify({'error': 'Invalid days parameter'}), 400
        
        # Order by date descending
        tips = query.order_by(TipEntry.work_date.desc()).all()

        result = []
        for tip in tips:
            tip_dict = tip.to_dict()
            tip_dict['user_name'] = tip.user.name if tip.user else None
            result.append(tip_dict)

        return jsonify({'tips': result})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/tips/<int:tip_id>', methods=['DELETE'])
@require_auth
def delete_tip_entry(tip_id):
    """Delete a tip entry"""
    try:
        current_user = get_current_user()

        if not current_user:
            return jsonify({'error': 'Authentication required'}), 401

        user = User.query.filter_by(id=current_user['id']).first()
        query = TipEntry.query.filter_by(id=tip_id)
        if not user or user.role != 'manager':
            query = query.filter_by(user_id=current_user['id'])

        tip = query.first()
        if not tip:
            return jsonify({'error': 'Tip entry not found'}), 404

        db.session.delete(tip)
        db.session.commit()

        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@api_bp.route('/stats/daily', methods=['GET'])
@require_auth
def get_daily_stats():
    """Get daily tip statistics"""
    try:
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'Authentication required'}), 401
        
        demo_mode = request.args.get('demo', 'false').lower() == 'true'
        
        if demo_mode:
            return jsonify(get_demo_data('daily_stats'))
        
        # Date filtering (same as get_tips)
        days = request.args.get('days', '30')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Build query
        query = db.session.query(
            TipEntry.work_date,
            func.sum(TipEntry.cash_tips).label('total_cash'),
            func.sum(TipEntry.card_tips).label('total_card'),
            func.sum(TipEntry.total_tips).label('total_tips'),
            func.sum(TipEntry.hours_worked).label('total_hours'),
            func.avg(TipEntry.tips_per_hour).label('avg_tips_per_hour')
        )
        
        # Role-based filtering
        user = User.query.filter_by(id=current_user['id']).first()
        if not user or user.role != 'manager':
            query = query.filter(TipEntry.user_id == current_user['id'])
        
        # Date filtering
        if start_date and end_date:
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
                query = query.filter(and_(
                    TipEntry.work_date >= start_date,
                    TipEntry.work_date <= end_date
                ))
            except ValueError:
                return jsonify({'error': 'Invalid date format'}), 400
        else:
            try:
                days_int = int(days)
                start_date = date.today() - timedelta(days=days_int)
                query = query.filter(TipEntry.work_date >= start_date)
            except ValueError:
                return jsonify({'error': 'Invalid days parameter'}), 400
        
        # Group by date and order
        daily_stats = query.group_by(TipEntry.work_date).order_by(TipEntry.work_date).all()
        
        result = []
        for stat in daily_stats:
            result.append({
                'date': stat.work_date.isoformat(),
                'total_cash': float(stat.total_cash or 0),
                'total_card': float(stat.total_card or 0),
                'total_tips': float(stat.total_tips or 0),
                'total_hours': float(stat.total_hours or 0),
                'avg_tips_per_hour': float(stat.avg_tips_per_hour or 0)
            })
        
        return jsonify({'daily_stats': result})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/stats/weekday', methods=['GET'])
@require_auth
def get_weekday_stats():
    """Get weekday average statistics"""
    try:
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'Authentication required'}), 401
        
        demo_mode = request.args.get('demo', 'false').lower() == 'true'
        
        if demo_mode:
            return jsonify(get_demo_data('weekday_stats'))
        
        # Build query for weekday averages
        query = db.session.query(
            TipEntry.weekday,
            func.avg(TipEntry.cash_tips).label('avg_cash'),
            func.avg(TipEntry.card_tips).label('avg_card'),
            func.avg(TipEntry.total_tips).label('avg_tips'),
            func.avg(TipEntry.hours_worked).label('avg_hours'),
            func.avg(TipEntry.tips_per_hour).label('avg_tips_per_hour')
        )
        
        # Role-based filtering
        user = User.query.filter_by(id=current_user['id']).first()
        if not user or user.role != 'manager':
            query = query.filter(TipEntry.user_id == current_user['id'])
        
        # Date filtering (last 90 days by default for meaningful averages)
        days = request.args.get('days', '90')
        try:
            days_int = int(days)
            start_date = date.today() - timedelta(days=days_int)
            query = query.filter(TipEntry.work_date >= start_date)
        except ValueError:
            pass
        
        # Group by weekday
        weekday_stats = query.group_by(TipEntry.weekday).order_by(TipEntry.weekday).all()
        
        # Map weekday numbers to names
        weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        
        result = []
        for stat in weekday_stats:
            result.append({
                'weekday': stat.weekday,
                'weekday_name': weekday_names[stat.weekday],
                'avg_cash': round(float(stat.avg_cash or 0), 2),
                'avg_card': round(float(stat.avg_card or 0), 2),
                'avg_tips': round(float(stat.avg_tips or 0), 2),
                'avg_hours': round(float(stat.avg_hours or 0), 2),
                'avg_tips_per_hour': round(float(stat.avg_tips_per_hour or 0), 2)
            })
        
        return jsonify({'weekday_stats': result})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/stats/breakdown', methods=['GET'])
@require_auth
def get_breakdown_stats():
    """Get cash vs card breakdown"""
    try:
        current_user = get_current_user()
        
        if not current_user:
            return jsonify({'error': 'Authentication required'}), 401
        
        demo_mode = request.args.get('demo', 'false').lower() == 'true'
        
        if demo_mode:
            return jsonify(get_demo_data('breakdown_stats'))
        
        # Build query for totals
        query = db.session.query(
            func.sum(TipEntry.cash_tips).label('total_cash'),
            func.sum(TipEntry.card_tips).label('total_card'),
            func.sum(TipEntry.total_tips).label('total_tips')
        )
        
        # Role-based filtering
        user = User.query.filter_by(id=current_user['id']).first()
        if not user or user.role != 'manager':
            query = query.filter(TipEntry.user_id == current_user['id'])
        
        # Date filtering
        days = request.args.get('days', '30')
        try:
            days_int = int(days)
            start_date = date.today() - timedelta(days=days_int)
            query = query.filter(TipEntry.work_date >= start_date)
        except ValueError:
            pass
        
        result = query.first()
        
        if result:
            total_cash = float(result.total_cash or 0)
            total_card = float(result.total_card or 0)
            total_tips = float(result.total_tips or 0)
        else:
            total_cash = total_card = total_tips = 0.0
        
        return jsonify({
            'breakdown': {
                'cash_tips': total_cash,
                'card_tips': total_card,
                'total_tips': total_tips,
                'cash_percentage': round((total_cash / total_tips * 100) if total_tips > 0 else 0, 1),
                'card_percentage': round((total_card / total_tips * 100) if total_tips > 0 else 0, 1)
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/user/role', methods=['GET'])
@require_auth
def get_user_role():
    """Get current user's role"""
    try:
        current_user = get_current_user()
        user = User.query.filter_by(id=current_user['id']).first()
        
        if not user:
            # Create user with default role
            user = User()
            user.id = current_user['id']
            user.email = current_user['email']
            user.name = current_user['name']
            user.role = 'server'
            db.session.add(user)
            db.session.commit()
        
        return jsonify({'role': user.role})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
