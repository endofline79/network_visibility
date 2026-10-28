export type Source = {
  id: string;
  title: string;
  state: "fresh" | "stale" | "unavailable" | "quiet" | "partial";
  observed_at: string | null;
  note: string;
};
export type Country = {
  last_seen?: string;
  activity_id?: string;
  code: string;
  name: string;
  count: number;
  percent: number;
  latitude: number | null;
  longitude: number | null;
};
export type Device = {
  id: string;
  name: string;
  ip: string;
  type: string;
  attachment: string;
  observed_at: string;
};
export type AlertItem = {
  fingerprint: string;
  rule: string;
  severity: "info" | "warning" | "critical";
  state: "firing" | "resolved";
  subject: string;
  summary: string;
  first_seen: string;
  last_seen: string;
  age_seconds: number;
  evidence_query: string;
};

export type Alerts = {
  mode: "demo" | "live";
  as_of: string;
  checker: "ok" | "silent" | "unknown";
  illustrative: boolean;
  open: AlertItem[];
  resolved: AlertItem[];
};

export type FreshnessState =
  "fresh" | "info" | "warning" | "critical" | "unavailable";

export type OpsHome = {
  mode: "demo" | "live";
  illustrative: boolean;
  as_of: string;
  window: { start: string; end: string; seconds: number; label: string };
  freshness: {
    id: string;
    title: string;
    state: FreshnessState;
    observed_at: string | null;
    age_seconds: number | null;
    note: string;
  }[];
  talkers: {
    state: "available" | "unavailable" | "partial";
    rows: { ip: string; bytes: number }[];
    note: string;
  };
  blocks: {
    state: "available" | "unavailable" | "partial";
    rows: {
      interface: string;
      source: string;
      destination: string;
      destination_port: number | null;
      protocol: string;
      count: number;
    }[];
    unparsed: number;
    note: string;
  };
  dns: {
    state: "available" | "unavailable" | "partial";
    domains: { name: string; queries: number }[];
    clients: { ip: string; name: string; queries: number }[];
    note: string;
  };
  gateway: {
    state: "up" | "down" | "unknown" | "unavailable";
    observed_at: string | null;
    summary: string;
    sample: string;
  };
  notes: string[];
};

export type AllowlistedHost = {
  id: string;
  class: string;
  name: string;
  dns_names: string[];
  ip: string;
  mac: string;
  notes: string;
};

export type DestinationCount = {
  name: string;
  queries: number;
};

export type DestinationHost = AllowlistedHost & {
  state: "available" | "unavailable" | "partial";
  queries: number | null;
  first_seen: string | null;
  last_seen: string | null;
  domains: DestinationCount[];
  sites: DestinationCount[];
  note: string;
};

export type Destinations = {
  mode: "demo" | "live";
  illustrative: boolean;
  as_of: string;
  window: { start: string; end: string; seconds: number; label: string };
  deduped: boolean;
  inventory: AllowlistedHost[];
  hosts: DestinationHost[];
  notes: string[];
};

export type Overview = {
  mode: "demo" | "live";
  as_of: string;
  window: { start: string; end: string; seconds: number; label: string };
  sources: Source[];
  metrics: {
    devices: number | null;
    infrastructure: number | null;
    router_bytes: number | null;
    capture_bytes: number | null;
    dns_queries: number | null;
    dns_blocked: number | null;
    firewall_blocks: number | null;
    destinations: number | null;
    busiest: {
      name: string;
      ip: string;
      bytes: number;
      identity_note: string;
    } | null;
    attention: number;
  };
  countries: Country[];
  locations: Location[];
  location_state: "available" | "withheld" | "unavailable";
  devices: Device[];
  recent: { id: string; time: string; text: string; source: string }[];
  trend: { time: string; bytes: number }[];
  coverage: string[];
  issues: string[];
  geo: {
    available: boolean;
    provider: string;
    age_days: number | null;
    build_utc?: string | null;
    grid_degrees?: number;
    max_mapped_areas?: number;
    uncertainty_note?: string;
  };
};

export type GlobeSnapshot = {
  mode: "demo" | "live";
  as_of: string;
  window: Overview["window"];
  refresh_seconds: number;
  state: "fresh" | "stale" | "partial" | "unavailable";
  observed_at: string | null;
  endpoints: number | null;
  countries: Country[];
  locations: Location[];
  geo: Overview["geo"];
  note: string;
};

export type Location = {
  id: string;
  country_code: string;
  country_name: string;
  region: string | null;
  cities: string[];
  other_city_labels: number;
  name: string;
  precision: "area" | "country" | "unknown" | "overflow";
  latitude: number | null;
  longitude: number | null;
  count: number;
  last_seen: string | null;
  activity_id: string | null;
  age_buckets: { last_seen: string; count: number }[];
  accuracy_radius_km: number | null;
  radius_known_count: number;
};
