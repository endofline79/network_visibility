export const firewallWindows = [
  "5m",
  "15m",
  "1h",
  "6h",
  "24h",
  "7d",
  "30d",
] as const;
export const dnsWindows = ["15m", "1h", "6h", "24h", "7d", "30d"] as const;

export type View = "overview" | "events" | "inventory" | "health" | "jev";
export type EventMode = "firewall" | "dns" | "system";
export type FirewallAction = "all" | "pass" | "block";
export type DnsOutcome = "" | "blocked" | "cached" | "forwarded" | "other";
export type Connection = string;
export type Route = {
  view: View;
  eventMode: EventMode;
  window: string;
  action: FirewallAction;
  dnsWindow: string;
  dnsOutcome: DnsOutcome;
  focusClients: boolean;
  connection: Connection;
};

const defaults: Route = {
  view: "overview",
  eventMode: "firewall",
  window: "15m",
  action: "all",
  dnsWindow: "15m",
  dnsOutcome: "",
  focusClients: false,
  connection: "",
};

function oneOf<T extends string>(
  value: string | null,
  choices: readonly T[],
  fallback: T,
): T {
  return choices.find((choice) => choice === value) ?? fallback;
}

export function parseHash(hash: string): Route {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  const separator = raw.indexOf("?");
  const path = separator < 0 ? raw : raw.slice(0, separator);
  const params = new URLSearchParams(
    separator < 0 ? "" : raw.slice(separator + 1),
  );
  if (path === "inventory" || path === "devices") {
    const requested = params.get("connection") || "";
    const connection = /^[A-Z_]{1,32}$/.test(requested) ? requested : "";
    return {
      ...defaults,
      view: "inventory",
      focusClients: params.get("focus") === "clients" || !!connection,
      connection,
    };
  }
  if (path === "jev") return { ...defaults, view: "jev" };
  if (path === "collection") return { ...defaults, view: "health" };
  if (path === "dns" || path === "activity/dns") {
    return {
      ...defaults,
      view: "events",
      eventMode: "dns",
      dnsWindow: oneOf(params.get("window"), dnsWindows, "15m"),
      dnsOutcome: oneOf(
        params.get("outcome"),
        ["", "blocked", "cached", "forwarded", "other"] as const,
        "",
      ),
    };
  }
  if (path === "activity/logs") {
    return {
      ...defaults,
      view: "events",
      eventMode: "system",
      window: oneOf(params.get("window"), firewallWindows, "15m"),
    };
  }
  if (path === "activity" || path === "activity/firewall") {
    return {
      ...defaults,
      view: "events",
      eventMode: "firewall",
      window: oneOf(params.get("window"), firewallWindows, "15m"),
      action: oneOf(
        params.get("action"),
        ["all", "pass", "block"] as const,
        "all",
      ),
    };
  }
  return {
    ...defaults,
    window: oneOf(params.get("window"), firewallWindows, "15m"),
  };
}

export function overviewHash(window = "15m"): string {
  return window === "15m"
    ? "#overview"
    : `#overview?window=${encodeURIComponent(window)}`;
}

export function firewallHash(
  window = "15m",
  action: FirewallAction = "all",
): string {
  const params = new URLSearchParams();
  if (window !== "15m") params.set("window", window);
  if (action !== "all") params.set("action", action);
  return `#activity/firewall${params.size ? `?${params}` : ""}`;
}

export function dnsHash(window = "15m", outcome: DnsOutcome = ""): string {
  const params = new URLSearchParams();
  if (window !== "15m") params.set("window", window);
  if (outcome) params.set("outcome", outcome);
  return `#activity/dns${params.size ? `?${params}` : ""}`;
}

export function logsHash(window = "15m"): string {
  return window === "15m"
    ? "#activity/logs"
    : `#activity/logs?window=${encodeURIComponent(window)}`;
}

export function devicesHash(
  focusClients = false,
  connection: Connection = "",
): string {
  const params = new URLSearchParams();
  if (focusClients || connection) params.set("focus", "clients");
  if (connection) params.set("connection", connection);
  return `#devices${params.size ? `?${params}` : ""}`;
}
