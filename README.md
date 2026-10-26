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
- **Date Filtering**: Last 7/30/90/365 days or custom date ranges
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

1. Set environment variables using your hosting provider's secrets manager. For local development, copy `.env.example` to `.env` and load it into your environment before starting Gunicorn.
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

`SUPABASE_REST_URL` is also accepted when `SUPABASE_URL` is absent (a trailing
`/rest/v1` is removed). Only the public anon key belongs in `SUPABASE_ANON_KEY`;
it is intentionally sent to the browser. Never put a service-role key there.
Database URLs have no hardcoded defaults. Optional `DATABASE_URL_FALLBACK`
must point to the same database. Existing SQLite fallback behavior is retained;
set `ALLOW_SQLITE_FALLBACK=0` to require the configured database.

Run `python -m pytest -q` for isolated tests. Tests force in-memory SQLite and
block outbound network calls; no Supabase data is created, updated, or deleted.
The optional integration API stays disabled by default. No integration schema
migration is applied automatically.

Application startup never creates or migrates database tables. Production requires
an already provisioned schema; schema changes remain a separate reviewed operation.
For a new local SQLite development database, explicitly set a SQLite `DATABASE_URL`
and run `flask --app main init-dev-db` before starting the app. This command creates
only browser tables and rejects PostgreSQL and automatic SQLite fallback. Tests
continue to create their own isolated schema explicitly.

### 5. Install Dependencies

The application uses these Python packages (install via pip):
```bash
pip install flask flask-cors flask-sqlalchemy python-dotenv supabase
```

## Scoped integration API (draft)

The opt-in API supports own-user reads, validated previews, and idempotent creation.
Both feature flags default to disabled. See [the integration contract](docs/integrations.md) for routes, consent requirements, setup, and rollout gates.


An optional API access page lets each existing signed-in user explicitly issue
and revoke separate read-only or read-and-create client credentials, expiring after 1 or 24 hours.
It is disabled by default behind `INTEGRATIONS_SELF_SERVICE_ENABLED=0` and requires
the separately reviewed integration schema and API enablement. It neither shares
login cookies with clients nor connects to third parties automatically. See the
integration contract for exact consent, security and activation requirements.
