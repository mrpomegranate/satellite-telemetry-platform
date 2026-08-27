-- 015_label_review_attribution.sql  |  labels (owned by telemetry-platform)
--
-- Accepting a model proposal is a human decision on the record, so it needs an
-- author and a timestamp of its own. `updated_at` cannot serve: any later edit
-- overwrites it, and the question the ATO asks is "who decided this was a real
-- anomaly, and when", not "when did this row last change".
--
-- Separate from `promoted_by` / `promoted_at`, which record the steward moving
-- a label into the golden tier. Review and promotion are different decisions
-- made by different roles, and collapsing them would lose the distinction.

ALTER TABLE labels.label
    ADD COLUMN IF NOT EXISTS reviewed_by uuid REFERENCES app.platform_user(id),
    ADD COLUMN IF NOT EXISTS reviewed_at timestamptz;

-- The review queue's hot path: proposals awaiting a verdict, oldest first.
CREATE INDEX IF NOT EXISTS idx_label_pending_review
    ON labels.label (created_at)
    WHERE review_status = 'proposed';

DO $$ BEGIN
    ALTER TABLE labels.label
        ADD CONSTRAINT label_reviewed_together
        CHECK ((reviewed_by IS NULL) = (reviewed_at IS NULL));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;