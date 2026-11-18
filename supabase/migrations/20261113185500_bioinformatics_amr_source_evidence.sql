-- Preserve TBProfiler resistance evidence without conflating drug, class,
-- mutation, annotation provenance, or textual confidence.
-- Nullable additions are backwards-compatible with existing canonical rows.
ALTER TABLE public.jl_bio_amr
  ADD COLUMN IF NOT EXISTS drug text,
  ADD COLUMN IF NOT EXISTS mutation text,
  ADD COLUMN IF NOT EXISTS annotation_source text,
  ADD COLUMN IF NOT EXISTS source_confidence text;
