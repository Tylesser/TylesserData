local addonName, ns = ...

-- Tylesser - Data: WoW Forever game data recorded by the Tylesser Collector while playing (the user and the people
-- they gave it to), merged and written into Data\*.lua by tools/collector/collect.py. Load on demand: an addon that
-- wants it calls C_AddOns.LoadAddOn("TylesserData") and then asks the API below (the one global, TylesserData).
--
-- Positions are uiMapID + percent (0-100, as the game's map pins and /way use). A thing can have several spots per
-- map; each spot has a count (how often it was seen there), the most seen first in the API's lists.

ns.data = {}

local API = {}
TylesserData = API

local function Data(name)
  return ns.data[name] or {}
end

-- { { map, x, y, n }, ... } from the stored { [map] = { x, y, n, x, y, n, ... } }, most seen first.
local function Spots(stored, onlyMap)
  local list = {}
  for map, flat in pairs(type(stored) == "table" and stored or {}) do
    if not onlyMap or map == onlyMap then
      for i = 1, #flat, 3 do
        list[#list + 1] = { map = map, x = flat[i], y = flat[i + 1], n = flat[i + 2] or 1 }
      end
    end
  end
  table.sort(list, function(a, b) return a.n > b.n end)
  return list
end
API.Spots = Spots

local function Copy(record, id)
  if type(record) ~= "table" then
    return nil
  end
  local out = {}
  for key, value in pairs(record) do
    out[key] = value
  end
  out.id = id
  if record.spots then
    out.spots = Spots(record.spots)
  end
  return out
end

function API.Built()
  return Data("built")
end

-- NPCs --------------------------------------------------------------------------------------------------------------------

function API.NPC(id)
  return Copy(Data("npcs")[id], id)
end

-- Every NPC seen on a map: { { id, name, x, y, n }, ... } (each NPC's most seen spot there).
function API.NPCsOnMap(map)
  local list = {}
  for id, npc in pairs(Data("npcs")) do
    local spot = Spots(npc.spots, map)[1]
    if spot then
      list[#list + 1] = { id = id, name = npc.name, title = npc.title, x = spot.x, y = spot.y, n = spot.n }
    end
  end
  table.sort(list, function(a, b) return (a.name or "") < (b.name or "") end)
  return list
end

local byName
-- NPC IDs by name (any case): several when NPCs share a name.
function API.FindNPC(name)
  if type(name) ~= "string" then
    return {}
  end
  if not byName then
    byName = {}
    for id, npc in pairs(Data("npcs")) do
      if type(npc.name) == "string" then
        local key = npc.name:lower()
        byName[key] = byName[key] or {}
        table.insert(byName[key], id)
      end
    end
  end
  return byName[name:lower()] or {}
end

-- Objects -----------------------------------------------------------------------------------------------------------------

function API.Object(id)
  return Copy(Data("objects")[id], id)
end

function API.ObjectsOnMap(map)
  local list = {}
  for id, object in pairs(Data("objects")) do
    for _, spot in ipairs(Spots(object.spots, map)) do
      list[#list + 1] = { id = id, name = object.name, x = spot.x, y = spot.y, n = spot.n }
    end
  end
  return list
end

-- Quests ------------------------------------------------------------------------------------------------------------------

function API.Quest(id)
  local quest = Data("quests")[id]
  if type(quest) ~= "table" then
    return nil
  end
  local out = Copy(quest, id)
  out.accepted = Spots(quest.accepted)
  out.objectiveSpots = {}
  for index, spots in pairs(quest.objectiveSpots or {}) do
    out.objectiveSpots[index] = Spots(spots)
  end
  return out
end

-- Quests a given NPC / object / item starts or ends: kind "npc" | "object" | "item", field "starts" | "ends".
function API.QuestsOf(kind, id, field)
  local list = {}
  for questID, quest in pairs(Data("quests")) do
    local ids = quest[field or "starts"] and quest[field or "starts"][kind]
    for _, other in ipairs(ids or {}) do
      if other == id then
        list[#list + 1] = questID
        break
      end
    end
  end
  table.sort(list)
  return list
end

-- Quests whose giver stands on a map (or that were taken there): { { id, title, level, x, y } }.
function API.QuestsOnMap(map)
  local list, npcs = {}, Data("npcs")
  for questID, quest in pairs(Data("quests")) do
    local spot
    for _, npcID in ipairs(quest.starts and quest.starts.npc or {}) do
      spot = spot or Spots(npcs[npcID] and npcs[npcID].spots, map)[1]
    end
    spot = spot or Spots(quest.accepted, map)[1]
    if spot then
      list[#list + 1] = { id = questID, title = quest.title, level = quest.level, x = spot.x, y = spot.y }
    end
  end
  table.sort(list, function(a, b) return (a.level or 0) < (b.level or 0) end)
  return list
end

-- Vendors -----------------------------------------------------------------------------------------------------------------

function API.Vendor(npcID)
  local vendor = Data("vendors")[npcID]
  return vendor and { id = npcID, seen = vendor.seen, items = vendor.items } or nil
end

-- Who sells an item: { { npc, name, price, stack, limit, costs } }, cheapest first.
function API.VendorsSelling(itemID)
  local list, npcs = {}, Data("npcs")
  for npcID, vendor in pairs(Data("vendors")) do
    local entry = vendor.items and vendor.items[itemID]
    if entry then
      list[#list + 1] = { npc = npcID, name = npcs[npcID] and npcs[npcID].name, price = entry.price,
        stack = entry.stack, limit = entry.limit, costs = entry.costs }
    end
  end
  table.sort(list, function(a, b) return (a.price or math.huge) < (b.price or math.huge) end)
  return list
end

-- Trainers ----------------------------------------------------------------------------------------------------------------

function API.Trainer(npcID)
  local trainer = Data("trainers")[npcID]
  return trainer and { id = npcID, type = trainer.type, services = trainer.services } or nil
end

function API.TrainersTeaching(spellID)
  local list = {}
  for npcID, trainer in pairs(Data("trainers")) do
    for _, service in pairs(trainer.services or {}) do
      if service.spell == spellID then
        list[#list + 1] = { npc = npcID, cost = service.cost, level = service.level }
        break
      end
    end
  end
  return list
end

-- Drops -------------------------------------------------------------------------------------------------------------------

-- What a source dropped: kind "npc" | "object" | "fishing" (id = uiMapID). { opened, items = { { item, chance,
-- average } } }, chance 0-1 = times / opened, most likely first.
function API.Loot(kind, id)
  local record = Data("loot")[kind .. ":" .. tostring(id)]
  if not record then
    return nil
  end
  local list = {}
  for itemID, pair in pairs(record.items or {}) do
    local opened = math.max(1, record.opened or 1)
    list[#list + 1] = { item = itemID, chance = math.min(1, pair[1] / opened), average = pair[2] / math.max(1, pair[1]),
      times = pair[1] }
  end
  table.sort(list, function(a, b) return a.chance > b.chance end)
  -- money = coins over moneyTimes windows that had coins; skillMin / skillMax = your fishing skill at the catches
  return { opened = record.opened or 0, items = list, money = record.money, moneyTimes = record.moneyTimes,
    skillMin = record.skillMin, skillMax = record.skillMax }
end

-- Where an item drops: { { kind, id, chance, opened } }, most likely first.
function API.Drops(itemID)
  local list = {}
  for key, record in pairs(Data("loot")) do
    local pair = record.items and record.items[itemID]
    if pair then
      local kind, id = key:match("^(%a+):(%d+)$")
      local opened = math.max(1, record.opened or 1)
      list[#list + 1] = { kind = kind, id = tonumber(id), chance = math.min(1, pair[1] / opened), opened = record.opened }
    end
  end
  table.sort(list, function(a, b) return a.chance > b.chance end)
  return list
end

-- Quests rewarding an item: { { quest, choice = true when picked from several } }.
function API.QuestsRewarding(itemID)
  local list = {}
  for questID, quest in pairs(Data("quests")) do
    for _, field in ipairs({ "rewards", "choices" }) do
      for _, reward in ipairs(quest[field] or {}) do
        if reward.item == itemID then
          list[#list + 1] = { quest = questID, title = quest.title, choice = field == "choices" or nil }
        end
      end
    end
  end
  return list
end

-- Quests that ask for an item at the end (handed in): { { quest, title, count, currencies = { [currencyID] = amount } } }
-- (currencies: what the quest rewards, base amounts before talents; Commerce Authority reads the Merchant's Favor a
-- Sealed crate gives from it, 2026-11-27).
function API.QuestsRequiring(itemID)
  local list = {}
  for questID, quest in pairs(Data("quests")) do
    for _, need in ipairs(quest.required or {}) do
      if need.item == itemID then
        list[#list + 1] = { quest = questID, title = quest.title, count = need.count, currencies = quest.currencies }
      end
    end
  end
  table.sort(list, function(a, b) return a.quest < b.quest end)
  return list
end

-- Everywhere an item comes from: { vendors = VendorsSelling, drops = Drops, quests = QuestsRewarding }.
function API.ItemSources(itemID)
  return { vendors = API.VendorsSelling(itemID), drops = API.Drops(itemID), quests = API.QuestsRewarding(itemID) }
end

-- The quests seen offered right after this one was handed in (its chain), most often first.
function API.QuestsAfter(questID)
  local list = {}
  for id, quest in pairs(Data("quests")) do
    local count = quest.after and quest.after[questID]
    if count then
      list[#list + 1] = { quest = id, title = quest.title, times = count }
    end
  end
  table.sort(list, function(a, b) return a.times > b.times end)
  return list
end

-- Services: NPCs and objects that do something for you ("mail", "bank", "auction", "stable", "guildbank", "inn",
-- "repair", "spirithealer"), on a map or anywhere: { { kind, id, name, x, y, map } }.
function API.Services(service, map)
  local list = {}
  for _, source in ipairs({ { "npc", Data("npcs") }, { "object", Data("objects") } }) do
    for id, record in pairs(source[2]) do
      for _, s in ipairs(record.services or {}) do
        if s == service then
          local spot = Spots(record.spots, map)[1]
          if spot or not map then
            list[#list + 1] = { kind = source[1], id = id, name = record.name, map = spot and spot.map,
              x = spot and spot.x, y = spot and spot.y }
          end
          break
        end
      end
    end
  end
  return list
end

-- Relations: the quests a creature / object / loot source moves on (its kills or its loot counted for an
-- objective), most often first: { { quest, title, objective, times } }.
function API.QuestsNeeding(kind, id)
  local list, key = {}, kind .. ":" .. tostring(id)
  for questID, quest in pairs(Data("quests")) do
    for index, causes in pairs(kind == "npc" and quest.objectiveNpcs or {}) do
      if causes[id] then
        list[#list + 1] = { quest = questID, title = quest.title, objective = index, times = causes[id] }
      end
    end
    for index, causes in pairs(quest.objectiveSources or {}) do
      if causes[key] then
        list[#list + 1] = { quest = questID, title = quest.title, objective = index, times = causes[key] }
      end
    end
  end
  table.sort(list, function(a, b) return a.times > b.times end)
  return list
end

-- The quest an item drops for (nil = not a quest item; true = a quest item whose quest wasn't told).
function API.QuestOfItem(itemID)
  return Data("questItems")[itemID]
end

-- Gathering nodes: objects gathered with "herb" or "mine", on a map or anywhere:
-- { { id, name, requires = { skill, level }, skillMin, x, y, map } }.
function API.GatherNodes(kind, map)
  local list = {}
  for id, object in pairs(Data("objects")) do
    if object.gather == kind then
      for _, spot in ipairs(Spots(object.spots, map)) do
        list[#list + 1] = { id = id, name = object.name, requires = object.requires, skillMin = object.skillMin,
          map = spot.map, x = spot.x, y = spot.y }
      end
    end
  end
  return list
end

-- Rares and treasures (the minimap's markers) on a map: { { id, name, kind, npcOrObject, x, y } }.
function API.Vignettes(map)
  local list = {}
  for id, v in pairs(Data("vignettes")) do
    for _, spot in ipairs(Spots(v.spots, map)) do
      list[#list + 1] = { id = id, name = v.name, atlas = v.atlas, kind = v.kind, object = v.id, map = spot.map,
        x = spot.x, y = spot.y }
    end
  end
  return list
end

-- A map's points of interest: { { id, name, description, x, y } }.
function API.POIs(map)
  local list = {}
  for id, poi in pairs(Data("pois")[map] or {}) do
    list[#list + 1] = { id = id, name = poi.name, description = poi.description, atlas = poi.atlas, x = poi.x, y = poi.y }
  end
  return list
end

-- A readable text: kind "object" / "item" and its ID (or "title" and the title): { title, pages }.
function API.Text(kind, id)
  return Data("texts")[kind .. ":" .. tostring(id)]
end

function API.Recipe(id)
  return Copy(Data("recipes")[id], id)
end

-- Recipes that make an item / use it as a reagent.
function API.RecipesMaking(itemID)
  local list = {}
  for id, recipe in pairs(Data("recipes")) do
    if recipe.product == itemID then
      list[#list + 1] = id
    end
  end
  return list
end

function API.RecipesUsing(itemID)
  local list = {}
  for id, recipe in pairs(Data("recipes")) do
    for _, reagent in ipairs(recipe.reagents or {}) do
      if reagent.item == itemID then
        list[#list + 1] = { recipe = id, count = reagent.count }
      end
    end
  end
  return list
end

-- Auction prices seen: the latest { time, price, quantity }, and the whole history (oldest first).
function API.Price(itemID)
  local history = Data("prices")[itemID]
  if not history or #history == 0 then
    return nil
  end
  local last = history[#history]
  return { time = last[1], price = last[2], quantity = last[3], history = history }
end

-- Dungeons and bosses -------------------------------------------------------------------------------------------------

function API.Instance(id)
  local instance = Data("instances")[id]
  if not instance then
    return nil
  end
  local out = Copy(instance, id)
  out.entrance = Spots(instance.entrance)
  out.encounters = {}
  for encounterID, encounter in pairs(Data("encounters")) do
    if encounter.instance == id then
      out.encounters[#out.encounters + 1] = encounterID
    end
  end
  table.sort(out.encounters)
  return out
end

function API.Instances()
  local list = {}
  for id, instance in pairs(Data("instances")) do
    list[#list + 1] = { id = id, name = instance.name, type = instance.type }
  end
  table.sort(list, function(a, b) return (a.name or "") < (b.name or "") end)
  return list
end

function API.Encounter(id)
  return Copy(Data("encounters")[id], id)
end

-- Places ----------------------------------------------------------------------------------------------------------------

-- The sub-zones seen on a map: { { name, zone, x, y } } (each at its most seen spot).
function API.AreasOnMap(map)
  local list = {}
  for name, area in pairs(Data("areas")[map] or {}) do
    local spot = Spots(area.spots, map)[1]
    if spot then
      list[#list + 1] = { name = name, zone = area.zone, x = spot.x, y = spot.y }
    end
  end
  table.sort(list, function(a, b) return a.name < b.name end)
  return list
end

-- The sub-zone nearest a spot (as far as the data has seen it).
function API.AreaAt(map, x, y)
  local best, bestDistance
  for name, area in pairs(Data("areas")[map] or {}) do
    for _, spot in ipairs(Spots(area.spots, map)) do
      local d = (spot.x - x) ^ 2 + (spot.y - y) ^ 2
      if not bestDistance or d < bestDistance then
        best, bestDistance = name, d
      end
    end
  end
  return best
end

function API.Discovered(name)
  return Data("discovered")[name]
end

function API.Graveyards(map)
  return Spots(Data("graveyards").spots, map)
end

-- Flight points -------------------------------------------------------------------------------------------------------------

-- What a flight costs, in copper (nil before its flight map was opened there).
function API.FlightCost(fromNode, toNode)
  local node = Data("taxi")[fromNode]
  return node and node.costs and node.costs[toNode]
end

-- Letters from NPCs and the game: { { sender, subject, money, text, items } }.
function API.Letters()
  local list = {}
  for _, letter in pairs(Data("mail")) do
    list[#list + 1] = letter
  end
  return list
end

-- How long a flight takes, in seconds (nil before it was flown).
function API.FlightTime(fromNode, toNode)
  return Data("flights")[fromNode .. "-" .. toNode]
end

function API.FlightPoint(nodeID)
  return Copy(Data("taxi")[nodeID], nodeID)
end

function API.FlightPoints(map)
  local list = {}
  for nodeID, node in pairs(Data("taxi")) do
    if not map or node.map == map then
      list[#list + 1] = Copy(node, nodeID)
    end
  end
  table.sort(list, function(a, b) return (a.name or "") < (b.name or "") end)
  return list
end
