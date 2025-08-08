-- Tip Tracker Database Schema
-- This file should be run in your Supabase SQL editor

-- Enable Row Level Security
ALTER DATABASE postgres SET row_security = on;

-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'server' CHECK (role IN ('server', 'manager')),
    restaurant_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create tip_entries table
CREATE TABLE IF NOT EXISTS tip_entries (
    id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    cash_tips DECIMAL(10, 2) NOT NULL DEFAULT 0 CHECK (cash_tips >= 0),
    card_tips DECIMAL(10, 2) NOT NULL DEFAULT 0 CHECK (card_tips >= 0),
    hours_worked DECIMAL(4, 2) NOT NULL CHECK (hours_worked > 0 AND hours_worked <= 24),
    work_date DATE NOT NULL,
    weekday INTEGER NOT NULL CHECK (weekday >= 0 AND weekday <= 6), -- 0=Monday, 6=Sunday
    total_tips DECIMAL(10, 2) NOT NULL DEFAULT 0,
    tips_per_hour DECIMAL(8, 2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_tip_entries_user_id ON tip_entries(user_id);
CREATE INDEX IF NOT EXISTS idx_tip_entries_work_date ON tip_entries(work_date);
CREATE INDEX IF NOT EXISTS idx_tip_entries_weekday ON tip_entries(weekday);
CREATE INDEX IF NOT EXISTS idx_tip_entries_user_date ON tip_entries(user_id, work_date);

-- Function to automatically update total_tips and tips_per_hour
CREATE OR REPLACE FUNCTION calculate_tip_totals()
RETURNS TRIGGER AS $$
BEGIN
    NEW.total_tips = NEW.cash_tips + NEW.card_tips;
    NEW.tips_per_hour = CASE 
        WHEN NEW.hours_worked > 0 THEN ROUND(NEW.total_tips / NEW.hours_worked, 2)
        ELSE 0
    END;
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for automatic calculations
DROP TRIGGER IF EXISTS trigger_calculate_tip_totals ON tip_entries;
CREATE TRIGGER trigger_calculate_tip_totals
    BEFORE INSERT OR UPDATE ON tip_entries
    FOR EACH ROW
    EXECUTE FUNCTION calculate_tip_totals();

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for users table
DROP TRIGGER IF EXISTS trigger_users_updated_at ON users;
CREATE TRIGGER trigger_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Enable Row Level Security
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE tip_entries ENABLE ROW LEVEL SECURITY;

-- RLS Policies for users table
-- Users can only see and update their own record
CREATE POLICY "Users can view own record" ON users
    FOR SELECT USING (auth.uid()::text = id);

CREATE POLICY "Users can update own record" ON users
    FOR UPDATE USING (auth.uid()::text = id);

CREATE POLICY "Users can insert own record" ON users
    FOR INSERT WITH CHECK (auth.uid()::text = id);

-- Managers can view all users in their organization (if restaurant_id is implemented)
CREATE POLICY "Managers can view all users" ON users
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM users u 
            WHERE u.id = auth.uid()::text 
            AND u.role = 'manager'
            AND (u.restaurant_id = users.restaurant_id OR users.restaurant_id IS NULL)
        )
    );

-- RLS Policies for tip_entries table
-- Servers can only see their own tip entries
CREATE POLICY "Users can view own tip entries" ON tip_entries
    FOR SELECT USING (auth.uid()::text = user_id);

CREATE POLICY "Users can insert own tip entries" ON tip_entries
    FOR INSERT WITH CHECK (auth.uid()::text = user_id);

CREATE POLICY "Users can update own tip entries" ON tip_entries
    FOR UPDATE USING (auth.uid()::text = user_id);

CREATE POLICY "Users can delete own tip entries" ON tip_entries
    FOR DELETE USING (auth.uid()::text = user_id);

-- Managers can view all tip entries in their organization
CREATE POLICY "Managers can view all tip entries" ON tip_entries
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM users u 
            WHERE u.id = auth.uid()::text 
            AND u.role = 'manager'
            AND (
                u.restaurant_id = (SELECT restaurant_id FROM users WHERE id = tip_entries.user_id)
                OR (SELECT restaurant_id FROM users WHERE id = tip_entries.user_id) IS NULL
            )
        )
    );

-- Create a view for easy querying of tip statistics
CREATE OR REPLACE VIEW tip_statistics AS
SELECT 
    te.user_id,
    u.name as user_name,
    u.email as user_email,
    te.work_date,
    te.weekday,
    te.cash_tips,
    te.card_tips,
    te.total_tips,
    te.hours_worked,
    te.tips_per_hour,
    CASE 
        WHEN te.weekday = 0 THEN 'Monday'
        WHEN te.weekday = 1 THEN 'Tuesday'
        WHEN te.weekday = 2 THEN 'Wednesday'
        WHEN te.weekday = 3 THEN 'Thursday'
        WHEN te.weekday = 4 THEN 'Friday'
        WHEN te.weekday = 5 THEN 'Saturday'
        WHEN te.weekday = 6 THEN 'Sunday'
    END as weekday_name
FROM tip_entries te
JOIN users u ON te.user_id = u.id;

-- Grant permissions on the view
ALTER VIEW tip_statistics ENABLE ROW LEVEL SECURITY;

-- RLS policy for the view
CREATE POLICY "View follows same rules as tip_entries" ON tip_statistics
    FOR SELECT USING (
        auth.uid()::text = user_id 
        OR EXISTS (
            SELECT 1 FROM users u 
            WHERE u.id = auth.uid()::text 
            AND u.role = 'manager'
            AND (
                u.restaurant_id = (SELECT restaurant_id FROM users WHERE id = tip_statistics.user_id)
                OR (SELECT restaurant_id FROM users WHERE id = tip_statistics.user_id) IS NULL
            )
        )
    );

-- Insert some example data (optional - remove in production)
/*
INSERT INTO users (id, email, name, role) VALUES
('00000000-0000-0000-0000-000000000001', 'server@example.com', 'Server Example', 'server'),
('00000000-0000-0000-0000-000000000002', 'manager@example.com', 'Manager Example', 'manager');
*/
