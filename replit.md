# Overview

Tip Tracker is a full-stack web application designed for restaurant servers to track their daily tips with role-based access control and analytics. The application provides an intuitive interface for logging cash tips, card tips, and hours worked, while offering comprehensive analytics through charts and statistics. It features Google OAuth authentication via Supabase, a demo mode for testing, and responsive design that works across desktop and mobile devices.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Frontend Architecture
The frontend uses a traditional server-rendered approach with vanilla JavaScript for interactivity. Bootstrap 5 with dark theme provides the responsive UI framework, while Chart.js handles data visualizations. The application follows a single-page architecture where different sections are shown/hidden based on authentication state and user interactions.

## Backend Architecture
Built on Flask with a modular blueprint structure:
- **Flask Application**: Main application factory pattern with CORS enabled
- **Blueprint Organization**: Separate modules for API routes (`api.py`) and authentication (`auth.py`)
- **SQLAlchemy ORM**: Database abstraction layer with declarative base models
- **Session Management**: Flask sessions for maintaining user state after Supabase authentication

## Database Design
Uses PostgreSQL via Supabase with two main entities:
- **Users Table**: Stores user profiles with role-based access (server/manager roles)
- **Tip Entries Table**: Stores individual tip records with computed fields for analytics
- **Row Level Security**: Implemented at the database level for data isolation
- **Computed Fields**: Total tips and tips-per-hour calculated automatically

## Authentication & Authorization
Hybrid authentication system combining Supabase Auth with Flask sessions:
- **Supabase OAuth**: Google Sign-In integration for secure authentication
- **Token Verification**: Server-side verification of Supabase access tokens
- **Flask Sessions**: Maintains user state across requests
- **Role-Based Access**: Server and manager roles with different permission levels

## Data Processing
The application includes validation and processing layers:
- **Input Validation**: Server-side validation for tip entry data with error handling
- **Demo Data Generation**: Synthetic data generation for testing and demonstration
- **Analytics Calculations**: Daily statistics, weekday averages, and tip trends computed from raw data

# External Dependencies

## Authentication Services
- **Supabase Auth**: Google OAuth provider and user management
- **Supabase Client**: JavaScript SDK for frontend authentication flows

## Database Services
- **Supabase PostgreSQL**: Hosted PostgreSQL database with Row Level Security
- **SQLAlchemy**: Python ORM for database operations

## Frontend Libraries
- **Bootstrap 5**: CSS framework with dark theme for responsive UI
- **Chart.js**: JavaScript charting library for analytics visualizations
- **Font Awesome**: Icon library for UI elements

## Python Backend Dependencies
- **Flask**: Web application framework
- **Flask-CORS**: Cross-origin resource sharing support
- **Flask-SQLAlchemy**: Database integration
- **PyJWT**: JSON Web Token handling for authentication
- **Supabase Python**: Server-side Supabase client

## Development Tools
- **Werkzeug ProxyFix**: WSGI middleware for proxy support
- **Python Logging**: Application logging and debugging