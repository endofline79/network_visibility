"""Parse the OPNsense filterlog message body, preserving unsupported records.

Field layout checked against OPNsense 26.7.1's installed filter/read_log.py.
Direction is relative to the logged interface, not Internet ingress/egress.
"""

import csv
import hashlib
import ipaddress


def parse_filterlog(record: dict, local_networks=()) -> dict:
    raw = str(record.get("_msg", ""))
    stamp = str(record.get("_time", ""))
    event = {
        "id": hashlib.sha256((stamp + str(record.get("hostname", "")) + raw).encode()).hexdigest()[:24],
        "time": stamp, "hostname": record.get("hostname", ""), "raw": raw,
        "action": "unknown", "interface": "", "direction": "", "protocol": "",
        "source": "", "destination": "", "source_port": None, "destination_port": None,
        "source_local": False, "destination_local": False, "parse_error": None,
    }
    try:
        if len(raw) > 32768:
            raise ValueError("Message exceeds parser size limit")
        parts = next(csv.reader([raw], strict=True))
        version = int(parts[8])
        if version == 4:
            protocol_number, protocol, length_at = int(parts[15]), parts[16], 17
        elif version == 6:
            protocol_number, protocol, length_at = int(parts[13]), parts[12], 14
        else:
            raise ValueError("Unsupported IP version")
        source, destination = map(ipaddress.ip_address, parts[length_at + 1:length_at + 3])
        if source.version != version or destination.version != version:
            raise ValueError("Address family does not match record")
        packet_bytes = int(parts[length_at])
        if packet_bytes < 0:
            raise ValueError("Negative packet length")
        source_port = destination_port = None
        # Noninitial fragments may have no transport fields; do not invent ports.
        if protocol_number in (6, 17) and len(parts) > length_at + 3:
            port_fields = parts[length_at + 3:length_at + 5]
            if len(port_fields) != 2:
                raise ValueError("Incomplete transport ports")
            if any(port_fields):
                source_port, destination_port = map(int, port_fields)
                if not all(0 <= p <= 65535 for p in (source_port, destination_port)):
                    raise ValueError("Invalid transport port")
        event.update({
            "rule": parts[3] or parts[0], "rule_number": parts[0], "reason": parts[5],
            "interface": parts[4], "action": parts[6], "direction": parts[7],
            "ip_version": version, "protocol": protocol.upper(), "protocol_number": protocol_number,
            "source": str(source), "destination": str(destination),
            "source_port": source_port, "destination_port": destination_port,
            "packet_bytes": packet_bytes,
            "source_local": any(source in n for n in local_networks),
            "destination_local": any(destination in n for n in local_networks),
        })
    except (ValueError, IndexError, StopIteration, csv.Error):
        event["parse_error"] = "Unrecognized or incomplete filterlog record; original message retained."
    return event


def public_endpoint(address: str, local_networks=()) -> bool:
    try:
        ip = ipaddress.ip_address(address)
        return ip.is_global and not ip.is_multicast and not any(ip in n for n in local_networks)
    except ValueError:
        return False
