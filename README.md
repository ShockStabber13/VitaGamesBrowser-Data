# VitaGamesBrowser Data

Public, downloadable PS Vita IGDB catalog, game artwork packs and genre metadata for VitaGamesBrowser.

## Automated IGDB refresh

This repository is self-contained: [the weekly updater](.github/workflows/update-vita-igdb.yml)
runs **every Sunday at 04:00 Singapore time** (Saturday 20:00 UTC).
It fetches IGDB PS Vita metadata and NoPayStation game-title IDs for matching,
builds cover packs, runs tests, checks that the new catalog and covers have not
shrunk unexpectedly, and commits the published outputs to `vita/` on `main`.

The updater needs these **GitHub Actions repository secrets**:
- `IGDB_CLIENT_ID`
- `IGDB_CLIENT_SECRET`

Add them under **Settings → Secrets and variables → Actions → New repository secret**.
They are Twitch/IGDB API application credentials. Without them scheduled runs cannot
fetch fresh IGDB data. `DATA_REPO_TOKEN` is **not** needed; this repository publishes
using its own GitHub Actions `GITHUB_TOKEN` with `contents: write`.

To run a refresh immediately, open **Actions → Update PS Vita IGDB catalog and artwork
→ Run workflow**. The generator and tests are stored in `tools/` and `tests/`.
The workflow does **not** depend on the deleted VitaGamesBrowser source repository.

## Published files

The `vita/` directory contains `igdb-library.tsv`, `igdb-vita-games.json`,
`genres.tsv`, `packs.tsv`, `vita-icons-*.zip`, and the 16 `covers-XX.pack`
shards plus their manifest and index. VitaGamesBrowser downloads and caches
these published assets.

**PKGj is separate:** Its game database is refreshed from the app's configured
NoPayStation TSV source via **Refresh PKGj packages** in VitaGamesBrowser Settings.
The IGDB workflow does not update the PKGj app cache.

This repository publishes game metadata and artwork only. It must not publish
NoPayStation package URLs, entitlement data, personal credentials or secrets.
Third-party artwork licensing and redistribution terms remain the distributor's responsibility.
