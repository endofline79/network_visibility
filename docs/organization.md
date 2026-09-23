# Organizing Visibility

The primary navigation answers questions about the network. Sources remain
visible within those views so their observations are not mistaken for one another.

| View | Question | Current content |
|---|---|---|
| Overview | What is happening across sources? | Source freshness, scoped firewall/DNS/client cards, firewall globe, current signals, 24-hour timeline |
| Activity | What happened? | Firewall decisions, Pi-hole DNS queries, all collected logs including UniFi CEF events |
| Devices | What is connected, and where? | Current UniFi devices, clients, switch/AP attachments |
| Collection | Is our data arriving? | Source/application intake counts, DNS poll/archival status, collector and location coverage |
| Jev trial | What does the model make of it? | Existing explicitly enabled, metered experiment |

DNS lives under Activity instead of becoming another appliance tab. Devices is
the existing inventory view with clearer navigation. `#inventory` and `#jev`
bookmarks remain valid; new links include `#activity/dns`, `#activity/firewall`,
`#activity/logs`, `#devices`, and `#collection`.

The 2026-09-23 deployed Overview adds filtered links such as
`#activity/dns?window=24h&outcome=blocked` and
`#devices?focus=clients&connection=WIRELESS`.
Overview keeps source times and denominators visible: firewall totals are logged
decisions, DNS totals are Pi-hole queries, and clients are a current UniFi
inventory. The map uses loaded firewall records; the hourly firewall chart uses
an aggregate query over the full past day. A recent-change feed awaits parsed
UniFi CEF events and durable event history.

## Next design decisions

1. Add a **device detail** page that brings together current attachment, recent
   firewall observations, and DNS activity. Preserve the source and observation
   time. An IP is an observation, not a permanent device identity; historical
   DHCP/MAC evidence is needed before claiming joins across time.
2. Parse UniFi CEF into **device events** (connect, disconnect, roam, configuration)
   inside Activity while preserving its original log. Sparse events need a
   last-seen timestamp, not a false failure because a five-minute window is empty.
3. Let Jev consume additional source context only as a separate, reviewable
   experiment with the existing off switch and allowance. Source integration
   never enables paid inference automatically.

The first organization pass changed navigation and added the DNS view. The
deployed dashboard now also contains the Overview summary. Cross-source device
history and a unified event schema remain future work.
