-- Screener Performance Optimization Indexes
-- Run this migration to optimize IKG queries used by screener

-- Index 1: entity_resolver.py:169 - Query on ikg_company_master.cin
CREATE INDEX IF NOT EXISTS idx_ikg_company_master_cin_fast 
  ON ikg_company_master(cin) WHERE cin IS NOT NULL;

-- Index 2: entity_resolver.py:213 - Composite index on nse_symbol and bse_scrip_code
CREATE INDEX IF NOT EXISTS idx_ikg_company_master_symbols 
  ON ikg_company_master(nse_symbol, bse_scrip_code) 
  WHERE nse_symbol IS NOT NULL OR bse_scrip_code IS NOT NULL;

-- Index 3: entity_resolver.py:267 - Query on ikg_company_master.isin
CREATE INDEX IF NOT EXISTS idx_ikg_company_master_isin_fast 
  ON ikg_company_master(isin) WHERE isin IS NOT NULL;

-- Index 4: entity_resolver.py:314 - GIN index for fuzzy name matching (already exists but ensure)
-- Already created in bootstrap: idx_ikg_company_master_name_trgm

-- Index 5: entity_resolver.py:226 - Indexes on ikg_entity_aliases
CREATE INDEX IF NOT EXISTS idx_ikg_entity_aliases_entity 
  ON ikg_entity_aliases(entity_id);
CREATE INDEX IF NOT EXISTS idx_ikg_entity_aliases_alias_lower 
  ON ikg_entity_aliases(lower(alias));
CREATE INDEX IF NOT EXISTS idx_ikg_entity_aliases_type 
  ON ikg_entity_aliases(alias_type);

-- Index 6: governance_score.py:269 - Query on shp_raw.cin
CREATE INDEX IF NOT EXISTS idx_shp_raw_cin_quarter 
  ON shp_raw(cin, quarter DESC) WHERE cin IS NOT NULL;

-- Index 7: governance_score.py:281 - Composite index on ikg_edges
CREATE INDEX IF NOT EXISTS idx_ikg_edges_to_label 
  ON ikg_edges(to_vertex_id, label);

-- Index 8: governance_score.py:303 - Query on auditor_history_raw
CREATE INDEX IF NOT EXISTS idx_auditor_history_cin_role 
  ON auditor_history_raw(cin, role, fiscal_year DESC) WHERE cin IS NOT NULL;

-- Index 9: governance_score.py:315 - Query on directors_raw with cessation filter
CREATE INDEX IF NOT EXISTS idx_directors_raw_cin_active 
  ON directors_raw(cin, cessation_date) WHERE cin IS NOT NULL;

-- Index 10: director_network.py:139 - Composite index for shared directors query
-- Note: from_vertex_id and label already indexed separately, add composite
CREATE INDEX IF NOT EXISTS idx_ikg_edges_to_label_from 
  ON ikg_edges(to_vertex_id, label, from_vertex_id);

-- Index 11: company_provenance.py:129 - Composite index on ikg_facts
CREATE INDEX IF NOT EXISTS idx_ikg_facts_subject_date 
  ON ikg_facts(subject_entity_id, as_of_date DESC);

-- Analyze tables to update query planner statistics
ANALYZE ikg_company_master;
ANALYZE shp_raw;
ANALYZE ikg_edges;
ANALYZE auditor_history_raw;
ANALYZE directors_raw;
ANALYZE ikg_entity_aliases;
ANALYZE ikg_facts;
