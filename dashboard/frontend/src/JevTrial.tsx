import { useEffect, useState } from "react";
import {
  Sparkles,
  Power,
  RefreshCw,
  ArrowRight,
  Check,
  CircleHelp,
} from "lucide-react";
import type { FirewallEvent } from "./types";
import { JevFeed } from "./JevFeed";

type Group = {
  id: string;
  source: string;
  destination: string;
  destination_port: number | null;
  protocol: string;
  action: string;
  interface: string;
  source_scope: string;
  destination_scope: string;
  count: number;
  first_seen: string;
  last_seen: string;
  examples: FirewallEvent[];
  role?: string;
  context?: string;
};
type Choice = {
  choice: string;
  confidence: number;
  probabilities: Record<string, number>;
};
export type Run = {
  id: string;
  started_at: string;
  finished_at?: string;
  trigger?: "manual" | "continuous";
  status: string;
  model: string;
  groups: Group[];
  answers: Record<string, { purpose: Choice; pattern: Choice }>;
  error: string | null;
  reviews?: Record<string, string>;
  sample_capped: boolean;
  payload?: unknown;
  sample?: {
    sample_events: number;
    total_events: number;
    total_groups: number;
    window_seconds: number;
    window_start: string | null;
    parse_errors: number;
  };
  usage: {
    input_tokens: number;
    output_tokens: number;
    estimated_cost_usd: number;
  } | null;
};
export type Status = {
  enabled: boolean;
  enabled_until: string | null;
  configured: boolean;
  busy: boolean;
  model: string;
  daily_limit: number;
  used_today: number;
  remaining_today: number;
  day_utc: string;
  group_limit: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  usage_unconfirmed: number;
  purposes: Record<string, string>;
  patterns: Record<string, string>;
  runs: Run[];
  mode: "manual" | "continuous";
  stream: {
    interval_seconds: number;
    session_id: string | null;
    next_run_at: string | null;
    capturing: boolean;
    message: string;
    last_sample: {
      as_of: string;
      sample_events: number;
      total_events: number;
      total_groups: number;
      selected_groups: number;
      selected_records: number;
      capped: boolean;
      parse_errors: number;
      window_seconds: number;
      skipped_seconds: number;
    } | null;
  };
};
type Preview = {
  id: string;
  as_of: string;
  sample_events: number;
  total_events: number;
  capped: boolean;
  parse_errors: number;
  total_groups: number;
  groups: Group[];
};
type Selection = { id: string; role: string; context: string };
type RequestPreview = {
  payload: { model: string; state: unknown; questions: unknown };
  request_bytes: number;
  api_requests: number;
};

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/jev/${path}`, {
    cache: "no-store",
    ...(body === undefined
      ? {}
      : {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Visibility-Trial": "1",
          },
          body: JSON.stringify(body),
        }),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "The trial request could not be completed.",
    );
  return data;
}
const time = (value: string) => new Date(value).toLocaleString();
const pct = (value: number) => `${Math.round(value * 100)}%`;
const roles: Record<string, string> = {
  unknown: "Unknown device role",
  workstation: "Workstation",
  server: "Server",
  phone: "Phone / tablet",
  tv: "TV / media player",
  game_console: "Game console",
  smart_home: "Smart-home device",
  network_device: "Network device",
  printer: "Printer",
};

export function JevTrial({
  onInspect,
}: {
  onInspect: (event: FirewallEvent) => void;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [connected, setConnected] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [selections, setSelections] = useState<Selection[]>([]);
  const [draft, setDraft] = useState<RequestPreview | null>(null);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [notice, setNotice] = useState("");
  const [activeRun, setActiveRun] = useState("");
  const [mode, setMode] = useState<"manual" | "continuous">("continuous");

  async function refreshStatus() {
    const next = await request<Status>("status");
    setStatus(next);
    setConnected(true);
    return next;
  }
  useEffect(() => {
    let alive = true;
    async function poll() {
      try {
        const next = await request<Status>("status");
        if (alive) {
          setStatus(next);
          setConnected(true);
          setConnectionError("");
          if (next.enabled) setMode(next.mode);
        }
      } catch (e) {
        if (alive) {
          setConnected(false);
          setConnectionError((e as Error).message);
        }
      }
    }
    void poll();
    // Local status only. This endpoint never contacts TypeSafe.
    const timer = setInterval(poll, 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  async function perform(label: string, action: () => Promise<void>) {
    setWorking(label);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setWorking("");
    }
  }
  function updateSelection(id: string, fields: Partial<Selection>) {
    setSelections((items) =>
      items.map((item) => (item.id === id ? { ...item, ...fields } : item)),
    );
    setDraft(null);
  }
  function toggleGroup(id: string) {
    setSelections((items) =>
      items.some((item) => item.id === id)
        ? items.filter((item) => item.id !== id)
        : [...items, { id, role: "unknown", context: "" }],
    );
    setDraft(null);
  }
  const chosenRun =
    status?.runs.find((run) => run.id === activeRun) || status?.runs[0];
  const activeMode = status?.enabled ? status.mode : mode;
  const following = !status?.runs.some((run) => run.id === activeRun);
  const selectedBody = { preview_id: preview?.id, groups: selections };
  const running = working === "Running" || status?.busy;
  const reviewed = chosenRun ? Object.entries(chosenRun.reviews || {}) : [];
  const agreed = reviewed.filter(
    ([id, label]) => chosenRun?.answers[id]?.purpose.choice === label,
  ).length;

  return (
    <div className="jev-trial">
      <section className="jev-control" aria-label="Jev spending controls">
        <div className="jev-intro">
          <span className="jev-icon">
            <Sparkles size={22} />
          </span>
          <div>
            <h2>Watch Jev interpret your network</h2>
            <p>
              Fresh observations in, model judgments out. See what Jev
              recognizes, where it hesitates, and what it cannot tell from the
              logs.
            </p>
          </div>
        </div>
        <div className="jev-modes" role="group" aria-label="Experiment mode">
          {(["continuous", "manual"] as const).map((value) => (
            <button
              key={value}
              aria-pressed={activeMode === value}
              disabled={
                !!status?.enabled ||
                !!status?.busy ||
                !!status?.stream.capturing ||
                !!working
              }
              onClick={() => {
                setMode(value);
                setError("");
                setNotice("");
              }}
            >
              {value === "continuous" ? "Continuous" : "Manual sample"}
            </button>
          ))}
        </div>
        <div className="jev-switch-row">
          <button
            className={`jev-toggle ${status?.enabled && connected ? "enabled" : ""}`}
            role="switch"
            aria-label="Enable metered Jev requests"
            aria-checked={!!status?.enabled && connected}
            disabled={
              !connected ||
              (!status?.enabled &&
                (!status?.configured ||
                  !status?.remaining_today ||
                  !!status?.busy ||
                  !!status?.stream.capturing))
            }
            onClick={() => {
              setError("");
              void request<Status>("control", {
                enabled: !status?.enabled,
                mode: activeMode,
              })
                .then((next) => {
                  setStatus(next);
                  if (next.enabled) setActiveRun("");
                })
                .catch((e: Error) => setError(e.message));
            }}
          >
            <Power size={17} />
            {!connected ? "Checking…" : status?.enabled ? "Jev on" : "Jev off"}
          </button>
          <p>
            {status?.enabled
              ? `${activeMode === "continuous" ? "Automatic batches" : "Manual runs"} · switches off at ${new Date(status.enabled_until!).toLocaleTimeString()}`
              : activeMode === "continuous"
                ? "Switch on to start automatic classification."
                : "Switch on to allow the manual Run button."}
          </p>
        </div>
        <p className="jev-fine">
          {activeMode === "continuous"
            ? "On starts a batch immediately, then up to three groups every minute. Runs on AI-02 even if you close this page."
            : "On unlocks Run; each click sends one batch."}{" "}
          Stops after 15 minutes or the daily limit. Off stops new calls; an
          active request may finish. Restarts switch Jev off.
        </p>
        {status && !status.configured && (
          <div className="notice">
            The server needs a TypeSafe API key. Local sample previews still
            work.
          </div>
        )}
        <div className="jev-meter">
          <div>
            <span>Requests today</span>
            <strong>
              {status ? `${status.used_today} / ${status.daily_limit}` : "—"}
            </strong>
            <small>Hard limit · resets at midnight UTC</small>
          </div>
          <div>
            <span>Recorded input tokens</span>
            <strong>{status?.input_tokens.toLocaleString() ?? "—"}</strong>
            <small>Across saved trial runs</small>
          </div>
          <div>
            <span>Estimated usage cost</span>
            <strong>
              {status ? `$${status.estimated_cost_usd.toFixed(6)}` : "—"}
            </strong>
            <small>Published input-token price · not an invoice</small>
          </div>
        </div>
        {!!status?.usage_unconfirmed && (
          <p className="jev-fine">
            {status.usage_unconfirmed} request(s) have unconfirmed usage. Their
            possible charges are not included in the estimate.
          </p>
        )}
      </section>

      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      {connectionError && (
        <div className="notice error" role="alert">
          Connection lost; the server may still be classifying until its limit
          or expiry. {connectionError}
        </div>
      )}
      {notice && (
        <div className="notice" role="status">
          <Check size={17} />
          {notice}
        </div>
      )}

      {activeMode === "continuous" && (
        <JevFeed
          status={status}
          connected={connected}
          onSelect={setActiveRun}
          following={following}
          onFollow={() => setActiveRun("")}
        />
      )}

      {activeMode === "manual" && (
        <>
          <section className="jev-panel">
            <div className="section-heading">
              <div>
                <div className="eyebrow">01 · PREVIEW LOCALLY</div>
                <h2>Choose the observations</h2>
                <p>
                  Capturing a sample and inspecting its records are free of Jev
                  usage.
                </p>
              </div>
              <button
                disabled={!!working || !!running}
                onClick={() =>
                  void perform("Capturing", async () => {
                    const next = await request<Preview>("preview", {});
                    setPreview(next);
                    setSelections([]);
                    setDraft(null);
                  })
                }
              >
                <RefreshCw
                  size={15}
                  className={working === "Capturing" ? "spinning" : ""}
                />
                {working === "Capturing"
                  ? "Capturing…"
                  : preview
                    ? "Capture new sample"
                    : "Capture sample"}
              </button>
            </div>
            {!preview && (
              <div className="jev-empty">
                <CircleHelp size={24} />
                <p>
                  Start with a snapshot of your actual firewall observations.
                  Nothing is sent to TypeSafe yet.
                </p>
              </div>
            )}
            {preview && (
              <>
                <p className="jev-fine">
                  Captured {time(preview.as_of)} ·{" "}
                  {preview.sample_events.toLocaleString()} log records · showing{" "}
                  {preview.groups.length} of {preview.total_groups} groups, with
                  different protocols first.
                </p>
                {preview.capped && (
                  <div className="notice">
                    This is a capped sample of the newest{" "}
                    {preview.sample_events.toLocaleString()} of{" "}
                    {preview.total_events.toLocaleString()} records. It does not
                    represent all network activity.
                  </div>
                )}
                {preview.parse_errors > 0 && (
                  <p className="jev-fine">
                    {preview.parse_errors} unparsed records are excluded from
                    this experiment.
                  </p>
                )}
                {!preview.groups.length && (
                  <div className="jev-empty">
                    No usable firewall groups in the last five minutes. Try
                    another sample after activity arrives.
                  </div>
                )}
                <div className="jev-groups">
                  {preview.groups.map((group, index) => {
                    const selected = selections.find(
                      (item) => item.id === group.id,
                    );
                    return (
                      <article
                        className={`jev-group ${selected ? "chosen" : ""}`}
                        key={group.id}
                      >
                        <label className="jev-group-choice">
                          <input
                            type="checkbox"
                            checked={!!selected}
                            aria-label={`Select activity group ${index + 1}`}
                            disabled={
                              !!working || (!selected && selections.length >= 3)
                            }
                            onChange={() => toggleGroup(group.id)}
                          />
                          <span>
                            <strong>
                              {group.protocol.toUpperCase()}{" "}
                              {group.destination_port === null
                                ? "control traffic"
                                : `port ${group.destination_port}`}
                            </strong>
                            <small>
                              {group.count.toLocaleString()} records ·{" "}
                              {group.action === "pass"
                                ? "allowed"
                                : group.action}
                            </small>
                          </span>
                        </label>
                        <div className="jev-endpoints">
                          <code>{group.source}</code>
                          <ArrowRight size={13} />
                          <code>{group.destination}</code>
                        </div>
                        <p className="jev-fine">
                          {group.source_scope} → {group.destination_scope}
                        </p>
                        <details>
                          <summary>
                            Observed evidence · {group.examples.length} sample
                            records
                          </summary>
                          <p className="jev-fine">
                            {time(group.first_seen)} — {time(group.last_seen)} ·
                            interface {group.interface}
                          </p>
                          {group.examples.map((event, i) => (
                            <button
                              className="jev-evidence"
                              key={i}
                              onClick={() => onInspect(event)}
                            >
                              {new Date(event.time).toLocaleTimeString()} ·
                              inspect raw record {i + 1}
                            </button>
                          ))}
                        </details>
                        {selected && (
                          <div className="jev-context">
                            <label>
                              Source device role (optional)
                              <select
                                value={selected.role}
                                disabled={!!working}
                                onChange={(e) =>
                                  updateSelection(group.id, {
                                    role: e.target.value,
                                  })
                                }
                              >
                                {Object.entries(roles).map(([value, label]) => (
                                  <option value={value} key={value}>
                                    {label}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <label>
                              Known context (optional)
                              <input
                                value={selected.context}
                                maxLength={200}
                                disabled={!!working}
                                placeholder="e.g. A backup job was running"
                                onChange={(e) =>
                                  updateSelection(group.id, {
                                    context: e.target.value,
                                  })
                                }
                              />
                            </label>
                            <small>
                              Role and context are included in the request.
                              Leave unknown details blank.
                            </small>
                          </div>
                        )}
                      </article>
                    );
                  })}
                </div>
                <div className="jev-actions">
                  <span>{selections.length} / 3 groups selected</span>
                  <button
                    disabled={!selections.length || !!working}
                    onClick={() =>
                      void perform("Preparing", async () => {
                        setDraft(
                          await request<RequestPreview>(
                            "request-preview",
                            selectedBody,
                          ),
                        );
                      })
                    }
                  >
                    Review request <ArrowRight size={15} />
                  </button>
                </div>
              </>
            )}
          </section>

          {draft && (
            <section className="jev-panel">
              <div className="eyebrow">02 · ONE MANUAL REQUEST</div>
              <h2>What Jev will see</h2>
              <p className="jev-fine">
                This sends the metadata below to TypeSafe. Raw logs, IP
                addresses, device names, and exact timestamps are omitted.
                Anything you entered as context is included.
              </p>
              <pre className="jev-payload">
                {JSON.stringify(draft.payload.state, null, 2)}
              </pre>
              <details>
                <summary>Full request, including category definitions</summary>
                <pre className="jev-payload">
                  {JSON.stringify(draft.payload, null, 2)}
                </pre>
              </details>
              <div className="jev-actions">
                <span>
                  {draft.request_bytes.toLocaleString()} request bytes ·{" "}
                  {selections.length} groups · {status?.model}
                </span>
                <button
                  className="jev-run"
                  disabled={
                    !status?.enabled ||
                    !connected ||
                    !!working ||
                    !!running ||
                    !status.remaining_today
                  }
                  onClick={() =>
                    void perform("Running", async () => {
                      const result = await request<{
                        run: Run;
                        cached: boolean;
                      }>("run", selectedBody);
                      setActiveRun(result.run.id);
                      await refreshStatus();
                      if (result.run.error) setError(result.run.error);
                      else
                        setNotice(
                          result.cached
                            ? "Saved result reused. No new API request was sent."
                            : "One request completed. Review the labels below; no more requests will run automatically.",
                        );
                    })
                  }
                >
                  <Sparkles size={16} />
                  {running ? "Request in progress…" : "Run 1 paid request"}
                </button>
              </div>
              {!status?.enabled && (
                <p className="jev-fine">
                  Use the Jev switch above to unlock Run. Previewing this
                  request has not used any API tokens.
                </p>
              )}
            </section>
          )}
        </>
      )}

      <section className="jev-panel">
        <div className="section-heading">
          <div>
            <div className="eyebrow">
              INSPECT A BATCH ·{" "}
              {following ? "FOLLOWING NEWEST" : "SAVED RESULT"}
            </div>
            <h2>Suggested activity labels</h2>
            <p>
              Inferences about the selected observations. These are not verified
              applications or bandwidth measurements.
            </p>
          </div>
          {!!status?.runs.length && (
            <select
              aria-label="Saved Jev trial"
              value={following ? "" : activeRun}
              onChange={(e) => setActiveRun(e.target.value)}
            >
              <option value="">Follow newest batch</option>
              {status.runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {time(run.started_at)} · {run.trigger || "manual"} ·{" "}
                  {run.status}
                </option>
              ))}
            </select>
          )}
        </div>
        {!chosenRun && (
          <div className="jev-empty">
            <Sparkles size={24} />
            <p>
              Your first result will appear here with its category probabilities
              and supporting observations.
            </p>
          </div>
        )}
        {chosenRun && (
          <>
            <div className="jev-result-meta">
              <span>
                {time(chosenRun.started_at)} · {chosenRun.model} ·{" "}
                {chosenRun.trigger || "manual"}
              </span>
              <span>
                {chosenRun.usage
                  ? `${chosenRun.usage.input_tokens.toLocaleString()} input tokens · estimated $${chosenRun.usage.estimated_cost_usd.toFixed(6)}`
                  : "Usage not yet confirmed"}
              </span>
            </div>
            {chosenRun.sample && (
              <p className="jev-fine">
                {chosenRun.groups.length} of {chosenRun.sample.total_groups}{" "}
                activity groups selected from{" "}
                {chosenRun.sample.sample_events.toLocaleString()} loaded /{" "}
                {chosenRun.sample.total_events.toLocaleString()} matching
                records in a {chosenRun.sample.window_seconds}-second window.
                {chosenRun.sample_capped ? " The input sample was capped." : ""}
                {chosenRun.sample.parse_errors
                  ? ` ${chosenRun.sample.parse_errors} unparsed records excluded.`
                  : ""}
              </p>
            )}
            {!!chosenRun.payload && (
              <details className="jev-sent-request">
                <summary>Exactly what this batch sent to Jev</summary>
                <pre className="jev-payload">
                  {JSON.stringify(chosenRun.payload, null, 2)}
                </pre>
              </details>
            )}
            {chosenRun.error && (
              <div className="notice error">{chosenRun.error}</div>
            )}
            {chosenRun.status === "started" && (
              <p className="jev-fine">
                This request is still in progress. Leaving the page does not
                cancel a request already started.
              </p>
            )}
            <div className="jev-results">
              {chosenRun.groups.map((group) => {
                const answers = chosenRun.answers[group.id];
                if (!answers) return null;
                const answer = answers.purpose;
                const categories = Object.entries(answer.probabilities).sort(
                  (a, b) => b[1] - a[1],
                );
                return (
                  <article className="jev-result" key={group.id}>
                    <div className="jev-result-label">
                      <Sparkles size={17} />
                      <h3>{status?.purposes[answer.choice]}</h3>
                    </div>
                    <p className="jev-fine">
                      {answer.choice === "unknown"
                        ? "Jev found insufficient evidence to assign a purpose."
                        : answer.confidence < 0.55
                          ? "Tentative suggestion · ambiguous choice distribution"
                          : "Model suggestion · verify against your own knowledge"}
                    </p>
                    <div className="jev-endpoints">
                      <code>{group.source}</code>
                      <ArrowRight size={13} />
                      <code>{group.destination}</code>
                    </div>
                    <p>
                      {group.protocol.toUpperCase()}{" "}
                      {group.destination_port === null
                        ? ""
                        : `:${group.destination_port}`}{" "}
                      · {group.count.toLocaleString()} observed records ·{" "}
                      {group.action}
                    </p>
                    <p className="jev-fine">
                      {status?.patterns[answers.pattern.choice]} · pattern
                      confidence {pct(answers.pattern.confidence)}
                    </p>
                    <div
                      className="jev-probabilities"
                      aria-label="Category probabilities"
                    >
                      {categories.slice(0, 4).map(([category, probability]) => (
                        <div key={category}>
                          <div>
                            <span>{status?.purposes[category]}</span>
                            <strong>{pct(probability)}</strong>
                          </div>
                          <div className="jev-bar">
                            <span style={{ width: pct(probability) }} />
                          </div>
                        </div>
                      ))}
                    </div>
                    <p className="jev-fine">
                      Choice confidence {pct(answer.confidence)}. Probability
                      and confidence describe the model’s judgment, not measured
                      accuracy.
                    </p>
                    <details>
                      <summary>Evidence and all category probabilities</summary>
                      <p className="jev-fine">
                        Role: {roles[group.role || "unknown"]}. Context:{" "}
                        {group.context || "None supplied"}. No DNS names or
                        prior device history were supplied.
                      </p>
                      {categories.map(([category, probability]) => (
                        <p className="jev-fine" key={category}>
                          {status?.purposes[category]}: {pct(probability)}
                        </p>
                      ))}
                      {group.examples.map((event, i) => (
                        <button
                          className="jev-evidence"
                          key={i}
                          onClick={() => onInspect(event)}
                        >
                          Inspect original record {i + 1}
                        </button>
                      ))}
                    </details>
                    <label className="jev-review">
                      Your label
                      <select
                        aria-label={`Your label for ${group.source} to ${group.destination}`}
                        value={chosenRun.reviews?.[group.id] || ""}
                        onChange={(e) =>
                          void perform("Saving label", async () => {
                            await request(`runs/${chosenRun.id}/review`, {
                              group_id: group.id,
                              category: e.target.value,
                            });
                            await refreshStatus();
                            setNotice(
                              "Your label was saved locally. No Jev request was sent.",
                            );
                          })
                        }
                        disabled={!!working}
                      >
                        <option value="" disabled>
                          Not reviewed yet
                        </option>
                        {Object.entries(status?.purposes || {}).map(
                          ([value, label]) => (
                            <option value={value} key={value}>
                              {label}
                            </option>
                          ),
                        )}
                      </select>
                      <small>
                        Saved locally for comparison; does not retrain Jev or
                        make an API call.
                      </small>
                    </label>
                  </article>
                );
              })}
            </div>
            {reviewed.length > 0 && (
              <p className="jev-fine">
                Agreement with your labels: {agreed} / {reviewed.length}{" "}
                reviewed groups in this run. This small sample is not an
                accuracy benchmark.
              </p>
            )}
          </>
        )}
      </section>
      <p className="jev-fine">
        Trial limits: three groups per request, ten attempted requests per UTC
        day, no automatic retries. Failed or interrupted attempts count toward
        the limit. Repeating an identical saved trial reuses its result.{" "}
        <a
          href="https://docs.typesafe.ai/models"
          target="_blank"
          rel="noreferrer"
        >
          Pricing reference
        </a>
        : $0.042 per million input tokens, output free; checked September 20,
        2026.
      </p>
    </div>
  );
}
