-- Match-MA: drop the silent research backoff column
-- Purpose: research throttling moves from a server-side rule nobody could see
-- to an explicit confirmation in the batch dialog.
--
-- research_retry_after was written after every sweep and read by nothing: the
-- enqueue path never consulted it, so the thirty day backoff it recorded was
-- never actually applied. Rather than wire up the silent version, the targets
-- list now carries last_research_at and the UI asks before re-researching
-- anything swept in the last thirty days - the consultant sees which targets
-- are affected and can override.
--
-- research_last_outcome stays: "last sweep found nothing public" is useful
-- context in that dialog.

begin;

alter table seller_target
  drop column if exists research_retry_after;

commit;
