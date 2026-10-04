import { useEffect, useState } from "react";

type Row = Record<string, string | number>;
type Data = {
  totals: Row; conversations: Row[]; sources: Row[]; destinations: Row[]; protocols: Row[];
  latest_flow: string | null; coverage: string;
  collector: { running: boolean; stale: boolean; pending_records?: number; insert_error?: boolean;
    invalid_records?: number; overflow_records?: number; rejected_datagrams?: number;
    datagrams?: number; decoded_records?: number; decoder_errors?: number | null;
    udp_receive_errors?: number | null; error?: string };
};
const count = (n: string | number | undefined) => Number(n || 0).toLocaleString();
const bytes = (n: string | number | undefined) => {
  const value = Number(n || 0);
  const unit = value ? Math.min(4, Math.floor(Math.log(value) / Math.log(1024))) : 0;
  return `${(value / 1024 ** unit).toLocaleString(undefined, {maximumFractionDigits: 2})} ${["B", "KiB", "MiB", "GiB", "TiB"][unit]}`;
};
export function Traffic({ onHealth }: { onHealth: (healthy: boolean) => void }) {
  const [window, setWindow] = useState("15m");
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let active = true;
    setData(null);
    async function update() {
      try {
        const response = await fetch(`/api/traffic?window=${window}`, {signal: abort.signal, cache: "no-store"});
        if (!response.ok) throw new Error(`Traffic query failed (${response.status})`);
        const next: Data = await response.json();
        if (active) {
          setData(next); setError("");
          onHealth(next.collector.running && !next.collector.stale && !next.collector.insert_error);
        }
      } catch (e) {
        if (active) { setError((e as Error).message); onHealth(false); }
      } finally { if (active) timer = setTimeout(update, 15000); }
    }
    update();
    return () => { active = false; abort.abort(); clearTimeout(timer); };
  }, [window, onHealth]);
  const c = data?.collector;
  return <div className="traffic-view">
    <div className="toolbar"><label>Traffic window <select aria-label="Traffic window" value={window} onChange={e => setWindow(e.target.value)}>
      {["5m", "15m", "1h", "6h", "24h", "7d", "30d"].map(v => <option key={v}>{v}</option>)}
    </select></label><span>Refreshes every 15 seconds · low-volume exports can lag several minutes</span></div>
    {error && <p role="alert">{error} — displayed data may be stale.</p>}
    {!data && !error && <p>Loading traffic…</p>}
    {data && <>
      <section className="health-card wide"><h2>Flow collection</h2>
        <p>{data.coverage}</p>
        <p>{c?.running && !c.stale && !c.insert_error ? "Receiving and storing flows" : "Collection needs attention — totals may be incomplete"}
          {c?.error && ` · ${c.error}`}</p>
        <p>Last flow: {data.latest_flow ? new Date(data.latest_flow).toLocaleString() : "None yet"} · Buffered: {count(c?.pending_records)} · Received datagrams: {count(c?.datagrams)} · Decoded records: {count(c?.decoded_records)}</p>
        <p>Rejected datagrams: {count(c?.rejected_datagrams)} · Invalid records: {count(c?.invalid_records)} · Buffer overflow losses: {count(c?.overflow_records)} · Decoder errors: {c?.decoder_errors == null ? "Unknown" : count(c.decoder_errors)} · UDP receive errors: {c?.udp_receive_errors == null ? "Unknown" : count(c.udp_receive_errors)}.</p>
        <p>Counters reset on collector restart. UDP delivery is best effort; these counters do not measure every upstream loss. After a decoder restart, data may be lost until templates refresh (up to 10 minutes plus export delay).</p>
      </section>
      <div className="traffic-summary"><section className="health-card"><h2>{bytes(data.totals.bytes)}</h2><p>Observed IP bytes</p></section>
        <section className="health-card"><h2>{count(data.totals.packets)}</h2><p>Observed packets</p></section>
        <section className="health-card"><h2>{count(data.totals.records)}</h2><p>Flow records, not sessions</p></section></div>
      <div className="traffic-summary">{([['Sources', 'src_addr', data.sources], ['Destinations', 'dst_addr', data.destinations], ['Protocols', 'proto', data.protocols]] as [string, string, Row[]][]).map(([title, key, rows]) =>
        <section className="health-card" key={title}><h2>Top {title.toLowerCase()}</h2><table><thead><tr><th>{title}</th><th>Bytes</th></tr></thead><tbody>{rows.map((r, i) => <tr key={i}><td>{r[key]}</td><td>{bytes(r.bytes)}</td></tr>)}</tbody></table></section>)}</div>
      <section className="health-card wide"><h2>Top 100 traffic tuples</h2><p>Grouped by source, destination, protocol and destination port. Totals above include all matching records, not just this table.</p>
        <div className="table-wrap"><table><thead><tr><th>Source</th><th>Destination</th><th>Protocol</th><th>Port</th><th>Bytes</th><th>Packets</th></tr></thead><tbody>{data.conversations.map((r,i) => <tr key={i}><td>{r.src_addr}</td><td>{r.dst_addr}</td><td>{r.proto}</td><td>{r.dst_port}</td><td>{bytes(r.bytes)}</td><td>{count(r.packets)}</td></tr>)}</tbody></table></div>
      </section>
    </>}
  </div>;
}
