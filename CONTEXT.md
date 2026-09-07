# Search glossary

Terms used for media searches and returned releases.

## Language

**Search candidate title**:
A title variant used to find releases. Candidate titles come from manager metadata
and anime metadata sources.

**Source release title**:
The original title supplied by Nyaa or an upstream Newznab provider.
A Nyaa release title is a source release title from Nyaa.

**Returned release title**:
The RSS item title sent to Sonarr or Radarr. It can be normalized from the source
release title to include the requested title and episode numbers.

**Confident match**:
A release whose parsed metadata meets the requested media identity and episode
or movie constraints. This term applies to results that pass local match filtering.

**Upstream Newznab provider**:
A configured Usenet indexer that supplies search results and NZB downloads.

**Manager**:
Sonarr or Radarr, which requests releases from the proxy.
