INSERT INTO state_priority (state_code, sort_weight, in_default_queue) VALUES
  ('OH', 120, true),
  ('CO', 130, true),
  ('NC', 140, true)
ON CONFLICT (state_code) DO NOTHING;
