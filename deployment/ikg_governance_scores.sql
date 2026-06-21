-- IGS Phase D — company_governance_scores history table (the productionised output).
--
-- One row per company per as-of date: the composite governance signal served to the
-- product, blending the deterministic rules engine (finagent.ikg.governance_score)
-- with the trained predictive model (finagent.ikg.igs.model). Keeping a dated history
-- (rather than overwriting in place) lets the product show trend, drives backtests,
-- and makes a long scoring run resumable.
--
-- Higher composite_score = more governance risk. band is recomputed from composite
-- using the GovernanceResult thresholds (<25 LOW, <50 MODERATE, <75 ELEVATED, else HIGH).
-- subscores/flags carry the citation-grade evidence so the score stays explainable.
--
-- Idempotent: safe to re-run. Materialised by finagent.ikg.igs.scoring.score_all_listed.

create table if not exists company_governance_scores (
    cin               text not null,
    as_of_date        date not null,
    composite_score   numeric,                 -- 0–100 blended risk (higher = worse)
    band              text,                     -- LOW | MODERATE | ELEVATED | HIGH
    rules_score       numeric,                  -- rules-engine score (0–100), if present
    model_risk        numeric,                  -- model predicted_risk (0–100), if present
    model_probability numeric,                  -- model failure probability (0–1), if present
    model_version     text,                     -- model_version, if a model contributed
    subscores         jsonb not null default '{}'::jsonb,
    flags             jsonb not null default '[]'::jsonb,
    source            text,                     -- rules | model | rules+model
    computed_at       timestamptz not null default now(),
    primary key (cin, as_of_date)
);

create index if not exists idx_company_governance_scores_asof
    on company_governance_scores (as_of_date);
create index if not exists idx_company_governance_scores_cin
    on company_governance_scores (cin);
