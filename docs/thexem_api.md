# TheXEM client reference

This page describes the requests made by
[app/services/thexem.py](../app/services/thexem.py). It is a reference for
maintainers of this client, not a complete upstream API specification.

## Requests

The client uses `https://thexem.info` as its base URL.

| Client method | GET path | Parameters |
| --- | --- | --- |
| `get_single_mapping` | `/map/single` | `id`, `origin`, and either `season` plus `episode`, or `absolute`. Optional `destination`. |
| `get_all_mappings` | `/map/all` | `id` and `origin`, which defaults to `tvdb`. |
| `get_all_names` | `/map/allNames` | `origin`. Optional `season`, `language`, and `defaultNames=1`. |

`id` identifies the show in the `origin` system. For a single mapping, the client
prefers `season` plus `episode` when both are supplied. If neither a complete pair
nor `absolute` is available, the client logs an error and returns `None`.

The client expects a JSON response with `result="success"` and reads its `data`
field. Request failures and unsuccessful responses return `None`.

## Episode conversion

`tvdb_to_anidb_episode(tvdb_id, season, episode)` requests a single mapping with
`origin=tvdb` and `destination=anidb`. It returns the nonzero `absolute` value from
the `anidb` entry, or `None` when unavailable.

A mapping entry has this shape. These values are illustrative:

```json
{
  "anidb": {"season": 1, "episode": 3, "absolute": 3},
  "tvdb": {"season": 1, "episode": 3, "absolute": 3}
}
```

Episode mapping entries contain episode numbers. The client does not extract an
AniDB show ID from those entries.

## Names and caching

`get_all_names` converts show ID keys to integers. `get_names_by_tvdb_id` first
requests names with defaults included, then tries without defaults if needed.

The client caches successful `/map/all` and `/map/allNames` results for seven
days in `DATA_DIR/thexem_cache.json`. `/map/single` requests are not cached by this
client. The HTTP timeout is 10 seconds for episode mappings and 15 seconds for
names. `CACHE_TTL` does not control TheXEM caching.
