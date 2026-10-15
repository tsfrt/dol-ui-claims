CREATE TABLE IF NOT EXISTS "custom_rules" (
  "rule_id" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "prompt" TEXT NOT NULL,
  "rationale" TEXT NOT NULL DEFAULT '',
  "category" TEXT NOT NULL,
  "severity" TEXT NOT NULL,
  "sql_text" TEXT NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'draft',
  "backtest_json" TEXT,
  "author_model" TEXT,
  "created_by" TEXT NOT NULL,
  "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "validated_at" TIMESTAMP(3),
  "promoted_by" TEXT,
  "promoted_at" TIMESTAMP(3),
  "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "custom_rules_pkey" PRIMARY KEY ("rule_id")
);

CREATE INDEX IF NOT EXISTS "custom_rules_status_idx" ON "custom_rules" ("status");
