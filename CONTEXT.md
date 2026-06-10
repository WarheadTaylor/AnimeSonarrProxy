# Context Glossary

## Search Candidate Title

A title variant sent to Nyaa as part of a search query. Candidate titles come from
manager metadata and anime metadata sources, and are optimized for finding releases.

## Nyaa Release Title

The original release title returned by Nyaa RSS. This is preserved for logging,
debugging, and traceability, but it is not necessarily safe for Sonarr or Radarr to
parse directly.

## Returned Release Title

The normalized RSS item title returned by AnimeSonarrProxy to Sonarr or Radarr.
Returned release titles are shaped for the receiving manager's parser while keeping
useful release metadata from the Nyaa release title.

## Confident Match

A Nyaa result whose parsed release metadata matches the requested media identity and
episode or movie constraints closely enough to return to Sonarr or Radarr.
