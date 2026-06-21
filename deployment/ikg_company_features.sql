-- IGS Phase B — company_features store (the model's input).
--
-- One row per company per as-of date: temporal signals (pledge/holding trajectory,
-- board churn, auditor stability) + graph signals (enforcement proximity, RPT density)
-- materialised from the IKG so training and inference read a flat, fast table.
-- Point-in-time: features are computed "as of" a date so backtests never leak future.

create table if not exists company_features (
    cin           text not null,
    as_of_date    date not null,
    quarter       text,

    -- Pledge trajectory (shp_raw)
    pledge_pct                 numeric,
    pledge_pct_qoq_delta       numeric,   -- latest minus prior quarter
    pledge_slope_4q            numeric,   -- linear Δ%/quarter over last 4 quarters
    pledge_accel               numeric,   -- change in slope (2nd difference)
    promoter_holding_pct       numeric,
    holding_dilution_4q        numeric,   -- drop in promoter holding over window
    pledge_quarters_observed   int,

    -- Board (directors_raw + DIRECTOR_OF edges)
    director_count             int,
    board_churn_12m            numeric,   -- cessations / board size in last 12m
    recent_cessations_12m      int,

    -- Enforcement proximity (ikg_edges)
    own_enforcement_count      int,       -- direct ENFORCEMENT_ACTION_AGAINST on company
    director_enforcement_count int,       -- company directors named in any SEBI order
    enforcement_proximity_hops int,       -- 0 own / 1 director / 2 two-hop / null none

    -- Auditor stability (auditor_history_raw)
    auditor_count_5y           int,
    mid_term_auditor_change    boolean,

    -- Related-party density (RELATED_PARTY_TRANSACTION edges)
    rpt_party_count            int,
    rpt_relationship_types     int,

    -- Forensics (placeholders for Phase C extensions)
    beneish_m_score            numeric,
    accrual_ratio              numeric,

    feature_version            text not null default 'igs_features_v1',
    computed_at                timestamptz not null default now(),
    primary key (cin, as_of_date)
);

create index if not exists idx_company_features_asof on company_features (as_of_date);
create index if not exists idx_company_features_cin  on company_features (cin);
