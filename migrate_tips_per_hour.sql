-- Migration: Fix tips_per_hour to use net_tips instead of gross tips
-- Run this in Supabase SQL Editor
-- Date: 2026-02-11

-- Step 1: Add tip_out column if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'tip_entries' AND column_name = 'tip_out'
    ) THEN
        ALTER TABLE public.tip_entries
        ADD COLUMN tip_out numeric(10,2) NOT NULL DEFAULT 0 CHECK (tip_out >= 0);
    END IF;
END $$;

-- Step 2: Add net_tips column if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'tip_entries' AND column_name = 'net_tips'
    ) THEN
        ALTER TABLE public.tip_entries
        ADD COLUMN net_tips numeric(10,2) NOT NULL DEFAULT 0;
    END IF;
END $$;

-- Step 3: Update the trigger function to use net_tips for tips_per_hour
CREATE OR REPLACE FUNCTION public.calculate_tip_totals()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.total_tips := COALESCE(NEW.cash_tips, 0) + COALESCE(NEW.card_tips, 0);
    NEW.net_tips := NEW.total_tips - COALESCE(NEW.tip_out, 0);
    NEW.tips_per_hour := CASE
        WHEN COALESCE(NEW.hours_worked, 0) > 0
        THEN ROUND(NEW.net_tips / NEW.hours_worked, 2)
        ELSE 0
    END;
    NEW.tip_percentage := CASE
        WHEN COALESCE(NEW.sales_amount, 0) > 0
        THEN ROUND(NEW.total_tips / NEW.sales_amount * 100, 2)
        ELSE 0
    END;
    NEW.updated_at := now();
    RETURN NEW;
END $$;

-- Step 4: Recalculate net_tips and tips_per_hour for ALL existing entries
UPDATE public.tip_entries
SET
    net_tips = (COALESCE(cash_tips, 0) + COALESCE(card_tips, 0)) - COALESCE(tip_out, 0),
    tips_per_hour = CASE
        WHEN COALESCE(hours_worked, 0) > 0
        THEN ROUND(
            ((COALESCE(cash_tips, 0) + COALESCE(card_tips, 0)) - COALESCE(tip_out, 0)) / hours_worked,
            2
        )
        ELSE 0
    END;

-- Step 5: Drop and recreate the view to include tip_out and net_tips
DROP VIEW IF EXISTS public.tip_statistics;
CREATE VIEW public.tip_statistics AS
SELECT
    te.user_id,
    u.name AS user_name,
    u.email AS user_email,
    te.work_date,
    te.weekday,
    te.section,
    te.sales_amount,
    te.cash_tips,
    te.card_tips,
    te.tip_out,
    te.total_tips,
    te.net_tips,
    te.hours_worked,
    te.tips_per_hour,
    te.tip_percentage,
    CASE te.weekday
        WHEN 0 THEN 'Monday'
        WHEN 1 THEN 'Tuesday'
        WHEN 2 THEN 'Wednesday'
        WHEN 3 THEN 'Thursday'
        WHEN 4 THEN 'Friday'
        WHEN 5 THEN 'Saturday'
        WHEN 6 THEN 'Sunday'
    END AS weekday_name
FROM public.tip_entries te
JOIN public.users u ON u.id = te.user_id;
