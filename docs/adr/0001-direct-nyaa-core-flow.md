# 0001. Direct Nyaa Core Flow

## Status

Accepted

## Context

AnimeSonarrProxy previously supported a broader proxy model with Prowlarr, WebUI
mapping overrides, and multiple query services. The rewrite focuses on the core
manager flow: Sonarr or Radarr asks a Torznab endpoint for anime media, the proxy
searches Nyaa, parses the Nyaa release title, filters uncertain matches, and returns
a manager-friendly Torznab response.

Nyaa has its own RSS metadata, categories, filters, and search syntax. Keeping
Prowlarr as an equal backend would require preserving adapter behavior that is not
part of this v1 goal.

## Decision

Use direct Nyaa RSS as the only v1 search backend. The runtime API will not depend
on Prowlarr, WebUI mapping overrides, or the old multi-query services.

## Consequences

The core request path is smaller and easier to reason about, and Nyaa-specific
rate limiting, filtering, parsing, and title normalization can be tested directly.

Users who need Prowlarr fallback or a WebUI for manual overrides will need those
features rebuilt after the core flow is stable.
