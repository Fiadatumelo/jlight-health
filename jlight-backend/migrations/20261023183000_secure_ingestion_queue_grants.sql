-- Ensure the durable source-export queue is accessible only through the trusted runtime role.
BEGIN;
REVOKE ALL ON TABLE public.jlight_ingestion_queue FROM PUBLIC, anon, authenticated;
REVOKE ALL ON SEQUENCE public.jlight_ingestion_queue_id_seq FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.jlight_ingestion_queue TO jlight_runtime;
GRANT USAGE, SELECT ON SEQUENCE public.jlight_ingestion_queue_id_seq TO jlight_runtime;
COMMIT;