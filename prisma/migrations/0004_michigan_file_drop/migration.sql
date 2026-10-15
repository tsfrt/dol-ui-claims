INSERT INTO state_priority (state_code, sort_weight, in_default_queue) VALUES
  ('MI', 110, true)
ON CONFLICT (state_code) DO NOTHING;
