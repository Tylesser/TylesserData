# Tylesser - Data

**WoW Forever** game data shared by players: NPCs and where they stand, quests (who gives and ends them, what counts
for them, their texts and rewards), what creatures, chests, herbs and ore drop and how often, herbs and ore with the
skill they need, rares and treasures, vendors and trainers, flight points and flight times, dungeons, places and more.

It is built every week from the files players share with
[Tylesser - Collector](https://tylesser.com/tylessercollector/) on [tylesser.com/collect](https://tylesser.com/collect/).
Every player's newest file counts once, and the data holds nothing about players.

You only need it when an addon uses it: it loads when an addon asks for it, so it costs nothing until then. Tylesser
addons use it when it is installed.

## For addon authors

```lua
C_AddOns.LoadAddOn("TylesserData")
local D = TylesserData
D.NPC(197)                 -- { id, name, title, minLevel, maxLevel, spots = { { map, x, y, n } } ... }
D.NPCsOnMap(1429)          -- every NPC seen on a map, with its most seen spot
D.FindNPC("Marshal Dughan")
D.Object(1618), D.ObjectsOnMap(1429)
D.Quest(60)                -- title, level, objectives, starts / ends, accepted spots, objectiveSpots
D.QuestsOf("npc", 240, "starts"), D.QuestsOnMap(1429)
D.Vendor(1250), D.VendorsSelling(159)
D.Trainer(928), D.TrainersTeaching(spellID)
D.Loot("npc", 299), D.Drops(itemID)   -- chances 0-1
D.FlightPoint(2), D.FlightPoints(mapID), D.FlightTime(fromNode, toNode)   -- seconds
D.QuestsRewarding(itemID), D.ItemSources(itemID)   -- vendors, drops, quest rewards
D.QuestsAfter(questID)     -- the quests offered right after it (chains)
D.Services("mail", mapID)  -- also bank, auction, stable, guildbank, inn, repair, spirithealer
D.Instance(36), D.Instances(), D.Encounter(1144)
D.AreasOnMap(mapID), D.AreaAt(mapID, x, y), D.Discovered(name), D.Graveyards(mapID)
D.QuestsNeeding("npc", 299)       -- quests its kills (or loot) move on, with the objective
D.QuestOfItem(itemID)             -- the quest an item drops for
D.GatherNodes("herb", mapID)      -- herb / ore nodes with the skill they need
D.Vignettes(mapID), D.POIs(mapID)   -- rares / treasures, points of interest
D.Text("object", id)               -- a readable text's pages
D.Recipe(id), D.RecipesMaking(itemID), D.RecipesUsing(itemID)
D.Price(itemID)                    -- the latest auction price and its history
-- loot kinds: "npc", "object", "fishing" (uiMapID), "item" (containers), "skin", "pick", "mine", "herb"
D.Built()                  -- build date and counts
```

Positions are uiMapID and percent (0-100), as map pins and waypoints use.

## Feedback

Found a mistake in the data, or have an idea? Go to [tylesser.com/feedback](https://tylesser.com/feedback/#tylesserdata).
No GitHub account? Join the [Tylesser Discord](https://discord.gg/n2rEB6mRxF) and post in #bug-reports or #ideas.

## Installation

Install from CurseForge or Wago, or download the latest zip from
[Releases](https://github.com/Tylesser/TylesserData/releases) and extract it to `Interface/AddOns`. The folder must be
named `TylesserData`.

## More from Tylesser

The other Tylesser addons are on [tylesser.com](https://tylesser.com/tylesserdata/).

## Releasing (maintainers)

The weekly workflow (`.github/workflows/weekly.yml`) builds `Data/` from the uploads and releases when it changed.
By hand: `python build/collect.py build --from <folder of uploads>`, then tag `vX.Y.Z`.

## License

MIT, see [LICENSE](LICENSE).
