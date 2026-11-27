# Tylesser - Data

The game-data addon (2026-11-24, the user's request), public: data recorded by Tylesser - Collector
(`Addons/TylesserCollector`), uploaded by players on https://tylesser.com/collect/ (tylesser-site `upload/`: stores
each install's files on the lab server's volume, gives the newest per install as `/api/uploads/latest` with a
token), merged and written into `Data/*.lua` by `build/collect.py` (in this repo so the weekly Action can run it;
packager-ignored). Never edit `Data/` by hand: rebuild. Forever only (Interface 16001), LoadOnDemand.

- `build/collect.py`: one file per install (`DB.install`, the newest), `build/exclude.txt` (install IDs left out:
  bad uploads, removal requests), `seenBy` on each record and `TYLESSER_MIN_SOURCES` (repo variable, default 1;
  raise it once there are many uploads so one fake file can't add anything). Without `--from` it reads the user's
  own WTF file and `tools/collector/inbox`.
- `.github/workflows/weekly.yml`: Mondays 06:00 UTC (and by hand, with a dry run): download, build, and when the
  data changed (not just `Data/built.lua`): a CHANGELOG section, commit, tag, packager in the same job (a tag pushed
  with GITHUB_TOKEN starts no other workflow). Secrets: `TYLESSER_UPLOADS_TOKEN`, `CF_API_KEY`.

- `TylesserData.lua`: `ns.data` (filled by the Data files) and the one global `TylesserData` (the API, see
  README.md). Spots are stored flat per map (`{ x, y, n, x, y, n }`) and handed out as `{ map, x, y, n }` lists,
  most seen first.
- Readers (2026-11-27, the user's "do 2-7"): Commerce Authority and Codex's Commerce module load it on demand
  (`Collected()` in their Core.lua) for writ NPCs missing from their table (`Quest(writQuest).ends.npc` + `NPC().spots[1]`),
  crate Favor (`QuestsRequiring(sealedCrate)` + `currencies[3402]`) and Waylaid Herbs' bill (`Text("item", 275642)`).
  Quest pins, map extras and drop info in tooltips: still the user's call.
- No data-source names here: the data comes from the user's own collecting (notes in `tools/collector/README.md`).
- Tests: `python -I tools/collector/test_collect.py` (merge + build into a temporary copy, then
  `tools/harness/data_test.lua` / `data_real_test.lua` over the API; uploads --from a folder, one file per install,
  exclusions, the minimum).
