export type Geo = {
  country_code: string;
  country: string;
  city: string;
  latitude: number;
  longitude: number;
};
export type FirewallEvent = {
  id: string;
  time: string;
  hostname: string;
  raw: string;
  action: string;
  interface: string;
  direction: string;
  protocol: string;
  source: string;
  destination: string;
  source_port: number | null;
  destination_port: number | null;
  source_local: boolean;
  destination_local: boolean;
  parse_error: string | null;
  rule?: string;
  rule_number?: string;
  reason?: string;
  ip_version?: number;
  packet_bytes?: number;
};
export type Snapshot = {
  as_of: string;
  window: string;
  window_seconds: number;
  events: FirewallEvent[];
  locations: Record<string, Geo>;
  lab: { latitude: number; longitude: number; label: string } | null;
  geoip: {
    available: boolean;
    build_time: string | null;
    age_days?: number;
    provider: string;
  };
  limit: number;
  capped: boolean;
  total: number;
  parse_errors: number;
  unlocated_public_ips: number;
  public_ips: number;
  last_event: string | null;
  oldest_event: string | null;
  query_ms: number;
  local_networks: string[];
  sources: { hostname: string; app_name: string; events: string }[];
};
export type LogRow = {
  time: string;
  hostname: string;
  application: string;
  message: string;
  severity: string;
  source: string;
};
export type LogResponse = {
  as_of: string;
  logs: LogRow[];
  capped: boolean;
  limit: number;
};
