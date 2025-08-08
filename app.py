import os
import logging
from flask import Flask, render_template
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix

# Configure logging
logging.basicConfig(level=logging.DEBUG)

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# Create the app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Enable CORS
CORS(app)

# Configure the database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "postgresql://localhost/tiptracker")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}

# Supabase configuration
app.config["SUPABASE_URL"] = os.environ.get("SUPABASE_URL", "")
app.config["SUPABASE_ANON_KEY"] = os.environ.get("SUPABASE_ANON_KEY", "")

# Initialize the app with the extension
db.init_app(app)

# Import routes and models
with app.app_context():
    import models
    import api
    import auth
    
    # Register blueprints
    app.register_blueprint(api.api_bp, url_prefix='/api')
    app.register_blueprint(auth.auth_bp, url_prefix='/auth')
    
    # Main route
    @app.route('/')
    def index():
        return render_template('index.html')
    
    # Create tables
    db.create_all()
