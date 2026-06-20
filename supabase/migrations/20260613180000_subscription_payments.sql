-- Subscription plan + deep-run quota tracking
-- Add columns to the existing public.profiles table (managed by Supabase Auth trigger)

ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'free',
ADD COLUMN IF NOT EXISTS deep_runs_used INTEGER NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS deep_runs_period_start TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_profiles_plan ON public.profiles(plan);

-- Payments table for verified Razorpay transactions
CREATE TABLE IF NOT EXISTS public.payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    razorpay_order_id TEXT NOT NULL,
    razorpay_payment_id TEXT,
    razorpay_signature TEXT,
    amount INTEGER NOT NULL, -- amount in paise
    currency TEXT NOT NULL DEFAULT 'INR',
    status TEXT NOT NULL DEFAULT 'pending',
    payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payments_user_id ON public.payments(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_order_id ON public.payments(razorpay_order_id);

ALTER TABLE public.payments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS payments_user_select ON public.payments;
CREATE POLICY payments_user_select ON public.payments
FOR SELECT TO authenticated USING (user_id = auth.uid());

DROP POLICY IF EXISTS payments_service_all ON public.payments;
CREATE POLICY payments_service_all ON public.payments
FOR ALL TO service_role USING (true) WITH CHECK (true);

GRANT USAGE ON SCHEMA public TO service_role, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.payments TO service_role;
GRANT SELECT ON public.payments TO authenticated;
