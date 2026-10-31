-- Remove the superseded legacy participant FK. The canonical link is study-scoped
-- and references jl_trial_participants(id, organisation_id) via the composite FK.
alter table private.jl_trial_recruitment_identity_links
 drop constraint if exists jl_trial_recruitment_identity_links_linked_participant_id_fkey;
