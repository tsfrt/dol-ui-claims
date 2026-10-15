CREATE TABLE "app_config" (
    "key" TEXT NOT NULL,
    "value" TEXT NOT NULL,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "app_config_pkey" PRIMARY KEY ("key")
);

CREATE TABLE "scoring_thresholds" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "ml_cutoff" DOUBLE PRECISION NOT NULL,
    "severity_high" DOUBLE PRECISION NOT NULL,
    "severity_med" DOUBLE PRECISION NOT NULL,
    "version" INTEGER NOT NULL DEFAULT 1,
    "active" BOOLEAN NOT NULL DEFAULT true,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "scoring_thresholds_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "rule_toggles" (
    "rule_id" TEXT NOT NULL,
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "label" TEXT NOT NULL,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "rule_toggles_pkey" PRIMARY KEY ("rule_id")
);

CREATE TABLE "state_priority" (
    "state_code" TEXT NOT NULL,
    "sort_weight" INTEGER NOT NULL DEFAULT 100,
    "in_default_queue" BOOLEAN NOT NULL DEFAULT true,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "state_priority_pkey" PRIMARY KEY ("state_code")
);

CREATE TABLE "cases" (
    "applicant_key" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'new',
    "assigned_to" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "cases_pkey" PRIMARY KEY ("applicant_key")
);

CREATE TABLE "case_notes" (
    "id" TEXT NOT NULL,
    "applicant_key" TEXT NOT NULL,
    "author" TEXT NOT NULL,
    "body" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "case_notes_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "analyst_dispositions" (
    "id" TEXT NOT NULL,
    "applicant_key" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "decision" TEXT NOT NULL,
    "rationale" TEXT NOT NULL,
    "author" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "analyst_dispositions_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "investigation_runs" (
    "id" TEXT NOT NULL,
    "applicant_key" TEXT NOT NULL,
    "conversation_id" TEXT,
    "prompt" TEXT NOT NULL,
    "report" TEXT NOT NULL DEFAULT '',
    "status" TEXT NOT NULL DEFAULT 'queued',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "investigation_runs_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "watchlist_adds" (
    "id" TEXT NOT NULL,
    "ssn_hash" TEXT NOT NULL,
    "label" TEXT NOT NULL,
    "author" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "watchlist_adds_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX "scoring_thresholds_name_key" ON "scoring_thresholds"("name");
CREATE INDEX "case_notes_applicant_key_idx" ON "case_notes"("applicant_key");
CREATE INDEX "analyst_dispositions_applicant_key_idx" ON "analyst_dispositions"("applicant_key");
CREATE INDEX "investigation_runs_applicant_key_idx" ON "investigation_runs"("applicant_key");

ALTER TABLE "case_notes" ADD CONSTRAINT "case_notes_applicant_key_fkey"
  FOREIGN KEY ("applicant_key") REFERENCES "cases"("applicant_key") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "analyst_dispositions" ADD CONSTRAINT "analyst_dispositions_applicant_key_fkey"
  FOREIGN KEY ("applicant_key") REFERENCES "cases"("applicant_key") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "investigation_runs" ADD CONSTRAINT "investigation_runs_applicant_key_fkey"
  FOREIGN KEY ("applicant_key") REFERENCES "cases"("applicant_key") ON DELETE CASCADE ON UPDATE CASCADE;
