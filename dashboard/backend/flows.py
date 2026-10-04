"""Read-only flow views, distinct from packet-filter decisions and Jev."""
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone


def collector_status():
    try:
        with urllib.request.urlopen(os.getenv("FLOW_COLLECTOR_URL", "http://flows:8081") + "/status", timeout=3) as response:
            return json.loads(response.read(16384))
    except Exception:
        return {"running": False, "stale": True, "error": "Flow collector unavailable"}


def build_traffic(query, window):
    seconds = {'5m':300, '15m':900, '1h':3600, '6h':21600, '24h':86400, '7d':604800, '30d':2592000}[window]
    end = datetime.now(timezone.utc)
    start = end - timedelta(seconds=seconds)
    base = f'_time:[{start.isoformat()},{end.isoformat()}) AND app_name:="opnsense-flow" AND schema:="2" AND remote_ip:="192.168.5.1"'
    # At-least-once delivery can repeat a receipt after an ambiguous HTTP ACK.
    # Collapse only identical event IDs, not distinct active-timeout records.
    unique = base + (' | stats by (event_id,src_addr,dst_addr,proto,src_port,dst_port,in_if,out_if)'
                     ' max(bytes) bytes, max(packets) packets')
    totals = query(unique + ' | stats sum(bytes) bytes, sum(packets) packets, count() records')
    conversations = query(unique + ' | stats by (src_addr,dst_addr,proto,dst_port) sum(bytes) bytes, sum(packets) packets, count() records | sort by (bytes) desc limit 100')
    sources = query(unique + ' | stats by (src_addr) sum(bytes) bytes | sort by (bytes) desc limit 20')
    destinations = query(unique + ' | stats by (dst_addr) sum(bytes) bytes | sort by (bytes) desc limit 20')
    protocols = query(unique + ' | stats by (proto) sum(bytes) bytes | sort by (bytes) desc limit 20')
    latest = query(base + ' | sort by (_time) desc limit 1 | fields _time')
    total = totals[0] if totals else {}
    total = {key: int(float(total.get(key, 0))) if str(total.get(key, '')).replace('.', '').isdigit() else 0
             for key in ('bytes', 'packets', 'records')}
    return {"window": window, "totals": total,
            "conversations": conversations, "sources": sources, "destinations": destinations,
            "protocols": protocols, "latest_flow": latest[0].get("_time") if latest else None,
            "collector": collector_status(), "retention_days": 30,
            "coverage": "OPNsense egress observations; no same-LAN switch traffic. Outbound Internet source addresses are post-NAT. Records are not sessions. Byte totals are IP-layer, not Ethernet wire bytes."}
