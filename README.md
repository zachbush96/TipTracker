# Tip Tracker - Restaurant Server Tip Tracking Application

A full-stack web application for restaurant servers to track their tips with role-based access control, analytics, and visualizations.

## Features

- **Authentication**: Google Sign-In via Supabase Auth
- **Role-based Access**: Server and Manager roles with appropriate permissions
- **Tip Tracking**: Easy form to log cash tips, card tips, and hours worked
- **Analytics Dashboard**: 
  - Daily tip trends
  - Cash vs card breakdown
  - Weekday averages
  - Tips per hour calculations
  - Average tips by section
- **Date Filtering**: Last 7/30/90 days or custom date ranges
- **Demo Mode**: Test the application with synthetic data
- **Responsive Design**: Works on desktop and mobile devices

## Tech Stack

### Backend
- **Flask**: Python web framework
- **SQLAlchemy**: Database ORM
- **Supabase**: PostgreSQL database with Row Level Security
- **Flask-CORS**: Cross-origin resource sharing

### Frontend
- **HTML5/CSS3**: Modern web standards
- **Bootstrap 5**: Responsive UI framework with dark theme
- **Vanilla JavaScript**: No frontend framework dependencies
- **Chart.js**: Beautiful, responsive charts
- **Supabase JS**: Client-side authentication

### Database
- **PostgreSQL**: Via Supabase
- **Row Level Security**: Automatic data isolation
- **Google OAuth**: Secure authentication

## Setup Instructions

### 1. Supabase Project Setup

1. Go to the [Supabase dashboard](https://supabase.com/dashboard/projects)
2. Create a new project
3. Wait for the project to be fully initialized

### 2. Database Schema Setup

1. In your Supabase project, go to the SQL editor
2. Copy the contents of `schema.sql` and run it
3. This will create the necessary tables, indexes, triggers, and RLS policies

### 3. Enable Google Authentication

1. In your Supabase project, go to Authentication → Providers
2. Enable Google provider
3. Add your domain to the allowed redirect URLs:
   - For development: `http://localhost:5000`
   - For production: `https://yourdomain.com`
4. Configure your Google OAuth credentials in the provider settings

### 4. Environment Configuration

1. Copy `.env.example` to `.env`
2. Fill in your Supabase credentials:
   ```env
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_ANON_KEY=your-anon-key
   DATABASE_URL=postgresql://postgres:[YOUR-PASSWORD]@db.your-project.supabase.co:5432/postgres
   SESSION_SECRET=generate-a-random-secret-key
   ```

3. Get your database URL:
   - In Supabase, click "Connect" → "Connection string" → "Transaction pooler"
   - Replace `[YOUR-PASSWORD]` with your actual database password

### 5. Install Dependencies

The application uses these Python packages (install via pip):
```bash
pip install flask flask-cors flask-sqlalchemy python-dotenv supabase
