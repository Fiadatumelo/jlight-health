-- Remove a mutation-blocking trigger if an earlier draft of the integrity guard
-- migration was applied. RLS policies remain the browser protection; privileged
-- retention and FK cascade operations must remain possible.
BEGIN;
DROP TRIGGER IF EXISTS jl_review_event_immutable_guard ON public.jl_finding_review_events;
DROP FUNCTION IF EXISTS public.jl_prevent_review_event_mutation();
COMMIT;
