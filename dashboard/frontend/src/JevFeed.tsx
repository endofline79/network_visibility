import { useState } from "react";
import { Activity, ArrowRight, Radio } from "lucide-react";
import type { Status } from "./JevTrial";

export function JevFeed({
  status,
  connected,
  onSelect,
  following,
  onFollow,
}: {
  status: Status | null;
  connected: boolean;
  onSelect: (id: string) => void;
  following: boolean;
  onFollow: () => void;
}) {
  const [filter, setFilter] = useState("");
  const live = connected && status?.enabled && status.mode === "continuous";
  const rows = (status?.runs || [])
    .filter((run) => run.trigger === "continuous")
    .flatMap((run) =>
      run.groups.flatMap((group) => {
        const answer = run.answers[group.id]?.purpose;
        return answer ? [{ run, group, answer }] : [];
      }),
    );
  const counts: Record<string, number> = {};
  for (const row of rows)
    counts[row.answer.choice] = (counts[row.answer.choice] || 0) + 1;
  const sample = status?.stream.last_sample;
  const nextIn = status?.stream.next_run_at
    ? Math.max(
        0,
        Math.ceil(
          (new Date(status.stream.next_run_at).getTime() - Date.now()) / 1000,
        ),
      )
    : null;
  const visible = rows.filter((row) => !filter || row.answer.choice === filter);

  return (
    <section
      className="jev-panel jev-feed"
      aria-label="Continuous Jev experiment"
    >
      <div className="section-heading">
        <div>
          <div className="eyebrow">LIVE EXPERIMENT · EVERY LABEL FROM JEV</div>
          <h2>
            <Radio size={20} /> Live Jev classifications
          </h2>
          <p>
            Automatic samples of fresh firewall activity. Each row is a group
            judged by the model.
          </p>
        </div>
        <span className={`jev-live-state ${live ? "active" : ""}`}>
          <span />
          {!connected ? "Disconnected" : live ? "Running" : "Stopped"}
        </span>
      </div>

      <div className="jev-stream-progress" role="status">
        <Activity
          size={18}
          className={
            live && (status?.busy || status?.stream.capturing) ? "spinning" : ""
          }
        />
        <div>
          <strong>
            {status?.stream.message || "Connecting to the experiment…"}
          </strong>
          {live &&
            !status?.busy &&
            !status?.stream.capturing &&
            nextIn !== null && (
              <small>
                {nextIn > 0
                  ? `Next batch in about ${nextIn}s`
                  : "Next batch is starting…"}
              </small>
            )}
          {sample && (
            <small>
              Latest window: {sample.window_seconds}s ·{" "}
              {sample.sample_events.toLocaleString()} loaded /{" "}
              {sample.total_events.toLocaleString()} matching records · selected{" "}
              {sample.selected_groups} of {sample.total_groups} groups
              {sample.capped ? " · capped input" : ""}
              {sample.parse_errors ? ` · ${sample.parse_errors} unparsed` : ""}
              {sample.skipped_seconds
                ? ` · ${sample.skipped_seconds}s collection gap`
                : ""}
            </small>
          )}
        </div>
      </div>

      <div
        className="jev-category-strip"
        aria-label="Categories in recent model decisions"
      >
        <button aria-pressed={!filter} onClick={() => setFilter("")}>
          All decisions <strong>{rows.length}</strong>
        </button>
        {Object.entries(counts)
          .sort((a, b) => b[1] - a[1])
          .map(([category, count]) => (
            <button
              key={category}
              aria-pressed={filter === category}
              data-category={category}
              onClick={() => setFilter(filter === category ? "" : category)}
            >
              <span className="jev-category-dot" />
              {status?.purposes[category]} <strong>{count}</strong>
            </button>
          ))}
      </div>

      {!rows.length ? (
        <div className="jev-empty">
          <Radio size={28} />
          <p>
            Switch Jev on above. The first batch will appear here automatically,
            followed by fresh activity each minute.
          </p>
        </div>
      ) : (
        <div className="jev-feed-table-wrap">
          <table className="jev-feed-table">
            <thead>
              <tr>
                <th>Batch time</th>
                <th>Observed activity</th>
                <th>Jev’s label</th>
                <th>Choice probability</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map(({ run, group, answer }) => (
                <tr key={`${run.id}-${group.id}`} data-category={answer.choice}>
                  <td>{new Date(run.started_at).toLocaleTimeString()}</td>
                  <td>
                    <strong>
                      {group.protocol.toUpperCase()}
                      {group.destination_port === null
                        ? ""
                        : ` :${group.destination_port}`}
                    </strong>
                    <small>
                      <code>{group.source}</code> <ArrowRight size={11} />{" "}
                      <code>{group.destination}</code>
                    </small>
                    <small>
                      {group.count} records · {group.action}
                    </small>
                  </td>
                  <td>
                    <span className="jev-feed-label">
                      <span className="jev-category-dot" />
                      {status?.purposes[answer.choice]}
                    </span>
                    {answer.choice !== "unknown" &&
                      answer.confidence < 0.55 && <small>Tentative</small>}
                  </td>
                  <td>
                    <strong>
                      {Math.round(answer.probabilities[answer.choice] * 100)}%
                    </strong>
                    <div className="jev-feed-probability">
                      <span
                        style={{
                          width: `${answer.probabilities[answer.choice] * 100}%`,
                        }}
                      />
                    </div>
                  </td>
                  <td>
                    <button
                      onClick={() => onSelect(run.id)}
                      aria-label={`Inspect batch ${new Date(run.started_at).toLocaleTimeString()} for ${group.protocol} port ${group.destination_port ?? "none"}`}
                    >
                      Inspect
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!visible.length && (
            <p className="jev-fine">
              No decisions in this category among the latest saved batches.
            </p>
          )}
        </div>
      )}
      <div className="jev-feed-footer">
        <p className="jev-fine">
          Continuous results within the latest 10 saved batches. Counts describe
          selected groups, not total traffic. Probabilities are model judgments,
          not measured accuracy.
        </p>
        {!following && <button onClick={onFollow}>Follow newest batch</button>}
      </div>
    </section>
  );
}
