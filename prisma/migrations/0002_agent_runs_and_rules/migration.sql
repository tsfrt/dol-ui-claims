ALTER TABLE "investigation_runs"
  ADD COLUMN IF NOT EXISTS "verdict" TEXT,
  ADD COLUMN IF NOT EXISTS "confidence" TEXT,
  ADD COLUMN IF NOT EXISTS "summary" TEXT,
  ADD COLUMN IF NOT EXISTS "steps_json" TEXT,
  ADD COLUMN IF NOT EXISTS "sql_count" INTEGER,
  ADD COLUMN IF NOT EXISTS "requested_by" TEXT,
  ADD COLUMN IF NOT EXISTS "error" TEXT,
  ADD COLUMN IF NOT EXISTS "completed_at" TIMESTAMP(3);

DELETE FROM "rule_toggles" WHERE "rule_id" !~ '^[A-Z]{2}-[0-9]{2}$';

INSERT INTO "rule_toggles" ("rule_id", "enabled", "label") VALUES
  ('FR-01', true, 'Deceased claimant'),
  ('FR-02', true, 'Incarcerated while certifying'),
  ('FR-03', true, 'Working while claiming'),
  ('FR-04', true, 'Concurrent interstate claims'),
  ('FR-05', true, 'SSA identity mismatch'),
  ('FR-06', true, 'Treasury Do Not Pay match'),
  ('EL-01', true, 'Monetarily ineligible'),
  ('EL-02', true, 'Disqualifying separation'),
  ('EL-03', true, 'Work search noncompliance'),
  ('EL-04', true, 'Paid beyond entitlement')
ON CONFLICT ("rule_id") DO NOTHING;

DELETE FROM "app_config" WHERE "key" IN ('demo_banner', 'queue_page_size', 'warehouse_id');
INSERT INTO "app_config" ("key", "value") VALUES
  ('genie_agent_id', ''),
  ('ml_flag_threshold', ''),
  ('queue_limit', '300'),
  ('agency_banner', 'U.S. Dept. of Labor · ETA')
ON CONFLICT ("key") DO NOTHING;
