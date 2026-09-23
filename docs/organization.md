# Organizing Visibility

The primary navigation answers questions about the network. Sources remain
visible within those views so their observations are not mistaken for one another.

| View | Question | Current content |
|---|---|---|
| Overview | What is happening geographically? | Existing firewall world map, logged decisions, countries |
| Activity | What happened? | Firewall decisions, Pi-hole DNS queries, all collected logs including UniFi CEF events |
| Devices | What is connected, and where? | Current UniFi devices, clients, switch/AP attachments |
| Collection | Is our data arriving? | Source/application intake counts, DNS poll/archival status, collector and location coverage |
| Jev trial | What does the model make of it? | Existing explicitly enabled, metered experiment |

DNS lives under Activity instead of becoming another appliance tab. Devices is
the existing inventory view with clearer navigation. `#inventory` and `#jev`
bookmarks remain valid; new links include `#activity/dns`, `#activity/firewall`,
`#activity/logs`, `#devices`, and `#collection`.

## Next design decisions

1. Add a **device detail** page that brings together current attachment, recent
   firewall observations, and DNS activity. Preserve the source and observation
   time. An IP is an observation, not a permanent device identity; historical
   DHCP/MAC evidence is needed before claiming joins across time.
2. Parse UniFi CEF into **device events** (connect, disconnect, roam, configuration)
   inside Activity while preserving its original log. Sparse events need a
   last-seen timestamp, not a false failure because a five-minute window is empty.
3. Evolve Overview into a network summary with clearly scoped DNS and device
   cards. Keep the map's denominator explicitly firewall observations; DNS lookup
   counts and UniFi inventory counts cannot be added to it as network traffic.
4. Let Jev consume additional source context only as a separate, reviewable
   experiment with the existing off switch and allowance. Source integration
   never enables paid inference automatically.

The first organization pass changes navigation and adds the DNS view. A full
cross-source device history, unified event schema, and overview redesign are
future work, not features implied by the new labels.
