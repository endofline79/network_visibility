# Jev activity classification experiment

Open **http://192.168.5.230:8095/#jev**. This is an experiment in classifying
observed home-network activity with Jev. Every activity label in the experiment
comes from the model. Grouping and sampling are ordinary code, with no rules
engine supplying or replacing the model's classifications.

## Watch continuous classification

1. Leave **Continuous** selected and switch **Jev on**. This starts the first
   automatic batch within about a second, then checks fresh activity every minute.
2. Watch **Live Jev classifications** populate. Category chips filter recent
   decisions. **Inspect** selects a batch in the detailed results below.
3. Expand **Exactly what this batch sent to Jev** or inspect original evidence.
   **Follow newest batch** returns the detail cards to following incoming results.
4. Switch **Jev off** to stop new paid requests. The existing daily allowance and
   15-minute expiry also stop the experiment automatically.

The worker runs inside the dashboard container on AI-02. Closing the browser or
switching dashboard views does not stop an enabled session. Browser polling only
reads saved results; it never initiates inference. A process restart starts OFF.

Each batch reads a non-overlapping time window within the current session, with
a five-second allowance for log delivery. The first window covers the preceding
minute. Each window loads at most 5,000 recent firewall records and selects up to
three groups, preferring protocols/services and groups less often selected in
that session. It groups by source, destination, destination port, protocol,
action, and interface. Every selected group is judged again on its fresh evidence;
this does not reuse a generic label for future traffic with the same port.

This is **continuous sampling, not classification of every record or all traffic**.
The page discloses matching and loaded records, selected and available groups,
parse failures, and caps. No activity means no paid request. It does not backfill
late records or activity while OFF. After a long worker delay, it reads at most
the latest two minutes and discloses the skipped interval. It is a bounded
experiment, not a durable all-events consumer. Device role remains unknown and
context remains empty in automatic batches; there is no inferred device inventory.

Category counts describe group judgments in continuous runs among the latest ten
saved batches, including unknown and tentative results. They are not traffic
shares, session counts, bandwidth, or an accuracy score. Older batches remain
stored locally but are outside this small live view.

## Inspect a manual sample

Switch Jev off, choose **Manual sample**, then:

1. Choose **Capture sample**. This reads the last five minutes from VictoriaLogs,
   groups the newest 5,000 firewall records, and offers up to 12 groups with
   different protocols/services first. Capped or unparsed data is disclosed.
2. Select one to three groups. Optionally supply the **source** device's role or
   known context. Inspect original records using the evidence buttons.
3. Choose **Review request**. This builds the exact request locally, without
   contacting TypeSafe. Inspect the metadata and full category definitions.
4. Switch **Jev on**, then choose **Run 1 paid request**. In manual mode, enabling
   does not itself run inference. One request asks two independent Choice questions per selected
   group: activity purpose and background/interactive/unknown pattern.
5. Compare the probability bars with the observations. Add **Your label** to
   save a local comparison. Corrections neither call nor retrain Jev.
6. Switch **Jev off**. Saved results remain viewable. The last ten runs are shown;
   older runs remain in the local database.

## Spending controls

- OFF at every dashboard process start; enabling expires after 15 minutes.
- Server checks the switch before starting a new run. A run already started may
  finish after switching off. The switch does not cancel an already billed call.
- Continuous mode sends at most one batch each minute while enabled; manual
  mode sends one batch per Run. Mode changes require switching off first.
  Repeated ON requests during an active session do not extend its expiry.
- There are no provider retries or backlog queues. A failed/unconfirmed model
  result, collection failure, or storage failure stops continuous mode. Inspect
  the saved batch before explicitly starting another session.
- One request per batch, at most three groups, at most 24,000 serialized request
  bytes. The backend constructs prompts; the browser cannot submit arbitrary
  prompts, model IDs, API endpoints, or larger batches.
- Hard limit of **ten attempted requests per UTC day**, shared by all clients.
  SQLite reserves each attempt before contacting TypeSafe. Failures, timeouts,
  and interrupted attempts consume the allowance. Toggle/restart cannot reset it.
- The ten attempts are shared by manual and continuous mode. With fresh activity
  every minute and a full allowance, continuous mode uses it in about ten minutes.
- One active request at a time. Identical evidence, context, model, and rubric
  reuse the saved response, including failed/unconfirmed attempts. A new sample
  with changed evidence/context is a new experiment. No automatic retry of an
  ambiguous timeout or interrupted request.
- Provider-reported input/output tokens and estimated input-token cost are
  recorded. Unknown usage is disclosed separately and excluded from that estimate.
  These are local measurements, not the provider's billing ledger.
- Model pinned to `jev-1.13.0`. Published price checked 2026-09-20:
  **$0.042 per million input tokens; output tokens free**.
  [TypeSafe models and pricing](https://docs.typesafe.ai/models).

## Data and interpretation

Raw logs, IP addresses, hostnames, exact timestamps, and interface names remain
local. The API request includes address scopes, protocol, destination port,
firewall action, record count, observed duration, and optional user-supplied role
and context. Anything entered in context is sent as entered; avoid secrets or
identifying details. The preview shows every outgoing field and question.

Purpose labels: network housekeeping, web/communication, streaming, gaming,
software updates, backup/sync, smart home, lab/development, and unknown. A role or
port is a clue, not application proof. No DNS names, application inspection,
bandwidth totals, or device history are available in this trial. Unknown is a
useful result. It is not a threat detector.

Probability bars compare the model's candidate labels. Choice confidence is a
summary of the probability distribution, not measured accuracy. The UI marks
non-unknown suggestions below 0.55 as tentative; this initial presentation
threshold is not validated calibration. Local reviewer labels permit comparing
results without changing the model's original answers. The code displays
observations directly; it does not claim Jev generated reasoning explanations.

## Configuration and persistence

New bind mounts belong only to the dashboard:

- `/home/klab/.local/share/visibility/dashboard` -> `/analysis`, writable.
  `trial.sqlite3` holds previews, attempts, usage, results, and reviewer labels.
- `/home/klab/.local/share/visibility/secrets` -> `/run/visibility-secrets`,
  read-only. `typesafe_api_key` is a 0600 file owned by UID 1000, obtained from
  existing Phase `Operator` / `Production` / `/typesafe` / `TYPESAFE_API_KEY`.

Neither directory is in the build context. The API key is never sent to the
browser or written to logs. The database is independent of VictoriaLogs retention;
no automatic trial-history deletion is implemented. These limits are intentionally
fixed for this experiment. Changing them requires a reviewed code update.

The API accepts JSON mutations only with a custom header and matching Origin
when present. This prevents cross-site browser triggers, but is **not user
authentication**. Reachable trusted LAN clients can use this shared trial and
allowance. Keep the current LAN-only access scope. The single Uvicorn process
owns the temporary enable switch, worker, sampling cursor, and active-run lock;
do not add processes/replicas without redesigning this coordination. SQLite
persists previews, attempts, complete request payloads, answers, usage, and reviews.
The worker's cursor and session stop on restart; it resumes only after a new ON.

## Validation and rollback

The Docker build runs parser, API, and trial tests. Trial tests use a fake provider
and never incur charges. They cover off/expiry enforcement, privacy of outgoing
fields, cache reuse, local reviews, persistent daily limits, failures, interrupted
requests, concurrency, storage failure, and browser mutation boundaries. Additional
worker tests cover automatic dispatch without browser polling, non-overlapping
windows, shutdown, off during capture/inference, sampling rotation, gaps/caps,
empty windows, mode races, and stopping at the shared daily limit.

Build and apply only the dashboard using the standard commands in
[dashboard operations](dashboard.md). Capture its existing image and Compose
file before deploying. The pre-continuous backup is
`state/jev-continuous-before-20260920/compose.yaml` on AI-02; its image is
`visibility-dashboard:0.2.0` (the manual trial). Version 0.3.0 adds the worker
without changing the existing database schema or secret mounts.

To stop paid requests, switch Jev off. To revert the dashboard, use the saved
Compose configuration, which selects the old image and old mounts:

```bash
cd /home/klab/codex/Visibility
docker compose -p visibility --env-file .env -f state/jev-continuous-before-20260920/compose.yaml up -d --no-deps --no-build --wait --wait-timeout 60 dashboard
```

This preserves both the log collector and trial data. After rollback, reconcile
the project Compose file with the selected version before a future normal update.
Do not remove data directories or use `docker compose down` for rollback.

API contract: [TypeSafe HTTP API](https://docs.typesafe.ai/api).
