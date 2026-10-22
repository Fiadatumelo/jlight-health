-- Prevent authenticated clients from fabricating review-history events directly.
-- The SECURITY DEFINER review RPC performs the authorised insert after checking
-- membership, action, finding scope, and authenticated actor.
BEGIN;
REVOKE INSERT, UPDATE, DELETE ON public.jl_finding_review_events FROM authenticated;
GRANT SELECT ON public.jl_finding_review_events TO authenticated;
REVOKE ALL ON FUNCTION public.jl_review_finding(uuid,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.jl_review_finding(uuid,text,text) TO authenticated;
COMMIT;
