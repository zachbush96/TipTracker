import os
from flask import Blueprint, request, jsonify, session
from supabase import create_client, Client
import jwt

auth_bp = Blueprint('auth', __name__)

# Initialize Supabase client
supabase_url = os.environ.get("SUPABASE_URL", "")
supabase_key = os.environ.get("SUPABASE_ANON_KEY", "")
supabase = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None

@auth_bp.route('/session', methods=['POST'])
def set_session():
    """Set user session from Supabase auth"""
    try:
        data = request.get_json()
        access_token = data.get('access_token')
        
        if not access_token:
            return jsonify({'error': 'Access token required'}), 400
        
        # Verify token with Supabase
        if supabase:
            try:
                user_response = supabase.auth.get_user(access_token)
                if user_response and user_response.user:
                    session['user'] = {
                        'id': user_response.user.id,
                        'email': user_response.user.email,
                        'name': user_response.user.user_metadata.get('name', '') if user_response.user.user_metadata else '',
                        'access_token': access_token
                    }
                    return jsonify({'success': True})
            except Exception as auth_error:
                return jsonify({'error': f'Authentication failed: {str(auth_error)}'}), 401
        
        return jsonify({'error': 'Invalid token'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Clear user session"""
    session.clear()
    return jsonify({'success': True})

@auth_bp.route('/user', methods=['GET'])
def get_user():
    """Get current user"""
    user = session.get('user')
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    
    return jsonify(user)

def get_current_user():
    """Helper function to get current user from session"""
    return session.get('user')

def require_auth(f):
    """Decorator to require authentication"""
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function
