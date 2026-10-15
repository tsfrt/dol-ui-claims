INSERT INTO app_config ("key", value) VALUES
  ('demo_banner', 'SYNTHETIC DATA — not live DOL or state UI systems'),
  ('queue_page_size', '50'),
  ('genie_agent_id', ''),
  ('warehouse_id', '')
ON CONFLICT ("key") DO NOTHING;

INSERT INTO scoring_thresholds (id, name, ml_cutoff, severity_high, severity_med, version, active)
VALUES ('thr_default', 'default', 0.72, 0.85, 0.55, 1, true)
ON CONFLICT (name) DO NOTHING;

INSERT INTO rule_toggles (rule_id, enabled, label) VALUES
  ('deceased_claimant', true, 'SSA death match'),
  ('incarcerated_claimant', true, 'Inmate match'),
  ('wage_while_claiming', true, 'NDNH wages while claiming'),
  ('interstate_duplicate', true, 'Concurrent multi-state claim'),
  ('identity_mismatch', true, 'SSA identity mismatch'),
  ('benefit_year_exhausted', true, 'Certifying after exhaustion'),
  ('watchlist_hit', true, 'SAM / OFAC analog hit'),
  ('filing_velocity', true, 'Rapid multi-state filings')
ON CONFLICT (rule_id) DO NOTHING;

INSERT INTO state_priority (state_code, sort_weight, in_default_queue) VALUES
  ('CA', 10, true),
  ('TX', 20, true),
  ('NY', 30, true),
  ('FL', 40, true),
  ('PA', 50, true),
  ('IL', 60, true),
  ('WA', 70, true),
  ('MA', 80, true),
  ('GA', 90, true),
  ('NJ', 100, true)
ON CONFLICT (state_code) DO NOTHING;
