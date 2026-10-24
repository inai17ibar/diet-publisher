# Weekly publish 502, 2026-10-24

Run: https://github.com/inai17ibar/diet-publisher/actions/runs/40061650682
Commit: 2ac2a4aa2112ab0f682e5b9f23ea67612d1b881e

## Evidence and limits

- Daily publish returned nothing_to_post at 04:15:58 UTC.
- Weekly publish returned 502 at 04:16:01, :11, :22, :32 UTC.
  Initial latency was about 3.2s; subsequent attempts about 0.25s, excluding
  curl's 10s retry delay. This is not evidence of a 180s timeout.
- The application maps DietMcpError (summary fetch) and InstagramStoryError
  (publication) to 502. Image/scoring/filesystem exceptions normally yield 500.
  Data fetch or Instagram failure is therefore more likely than image generation,
  assuming these responses originated from the application rather than Railway.
- Daily success makes a general Railway cold start less likely, but does not
  prove diet-mcp's weekly endpoint or Instagram was healthy. Daily may have
  skipped already-posted entries without fetching anything.
- Existing curl --fail discarded the response bodies. No Railway connector,
  CLI session, or credentials were available in the investigation environment.
  The historical cause remains unconfirmed; no claim of an external outage.
- No production publish endpoint was called and no workflow was rerun.

## Changes

- Retry only the read-only diet-mcp GET on transport errors and selected transient
  HTTP statuses, at most three attempts with 1s/2s delays. Authentication and
  other non-transient failures fail immediately. Invalid JSON/object shapes
  produce a controlled DietMcpError.
- Weekly errors return stage, week_start, request_id and exception class.
  Server logs add elapsed time and safe upstream HTTP status metadata.
  Raw exceptions, response bodies, tokens, image URLs and meal contents are
  deliberately excluded. AI comment failures log the fallback and remain optional.
- Weekly curl retains this safe response body and does not retry the entire POST.
  Existing ledger checks prevent ordinary subsequent posts, but are not an atomic
  exactly-once guarantee: publishing may succeed before ledger commit or before
  an HTTP response reaches the caller. Concurrent requests also remain a risk.
  This change does not redesign the Instagram publication protocol or daily POST.

## Next failure / recovery

1. Inspect weekly Actions response stage and request_id.
2. In Railway logs search that request_id and week_start. For fetch_week also
   inspect diet_mcp_failed upstream_status; inspect Fly.io logs for that period.
3. build_image/save_image means no external publish has yet been attempted.
   publish means external success may be uncertain; record_post means Instagram
   returned success but ledger persistence failed.
4. Before any manual retry, inspect the weekly ledger and Instagram account,
   especially for publish/record_post failures. Do not blindly rerun the job.
5. Only deploy after review: main pushes automatically deploy to Railway.
