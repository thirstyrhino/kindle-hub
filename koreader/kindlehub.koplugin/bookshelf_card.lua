--[[--
Kindle Hub card for Bookshelf's home screen (a Bookshelf "micro-module").

Shows one Kindle Hub screen as a native card, drawn with Bookshelf's own card kit so it sits
with the clock, reading stats and goal cards: the few lines each screen publishes as `tile`
in <site>/api/screens. Tap opens that screen full size (swipe for the others, tap to close).
Long-press → Module settings picks another screen. Add it once per screen you want, or once
as "What's on now", which follows the Kindle Hub schedule through the day.

Needs the Kindle Hub plugin (main.lua next to this file). That plugin puts a two-line loader
for this file in koreader/settings/bookshelf/micromodules/, where Bookshelf looks for cards,
so the card's code stays here and updates with the plugin.

Contract: https://github.com/AndyHazz/bookshelf.koplugin/blob/master/micromodules/README.md
]]

-- Loads in plain Lua too (Bookshelf's module checks run outside KOReader).
local ok_gettext, gettext = pcall(require, "gettext")
local _ = ok_gettext and gettext or function(s) return s end

local KEY = "kindlehub"
local STALE_LIST = 30 * 60      -- refetch the screen list when the saved one is older (site rebuilds hourly)
local RETRY_AFTER = 10 * 60     -- after a refetch attempt, wait this long before another
local OLD_DATA = 3 * 60 * 60    -- note the update time when the site itself hasn't rebuilt for this long

-- Set by the Kindle Hub plugin when it loads; nil when that plugin is turned off.
local function hub()
    local api = package.loaded["kindlehub/api"]
    if type(api) == "table" and api.version then return api end
    return nil
end

-- What a card shows: a screen name, or nil for "what's on now".
local function wanted(ctx)
    local v = ctx and ctx.config and ctx.config:get("kh_screen")
    if type(v) == "string" and v ~= "" then return v end
    return nil
end

local function findScreen(data, name)
    name = name or data.on_air
    for _, s in ipairs(data.screens or {}) do
        if s.name == name then return s end
    end
    if not name then return data.screens and data.screens[1] end
    return nil
end

-- Re-render callbacks of every Kindle Hub card on screen, so one fetch updates them all.
local refreshers = {}
local last_try = 0

local function refreshCards()
    for _, cb in pairs(refreshers) do pcall(cb) end
end

-- Background refetch of the list, only when Wi-Fi is already on: drawing the home screen
-- never turns Wi-Fi on or asks to. At most one try every RETRY_AFTER seconds.
local function maybeFetch(api, data)
    local age = api.listAge()
    if data and age and age < STALE_LIST then return end
    if os.time() - last_try < RETRY_AFTER then return end
    local ok, NetworkMgr = pcall(require, "ui/network/manager")
    if not (ok and NetworkMgr and NetworkMgr:isConnected()) then return end
    last_try = os.time()
    require("ui/uimanager"):scheduleIn(0.5, function()
        if api.refreshList() then refreshCards() end
    end)
end

-- The card itself: heading, big value + suffix, optional bar, sub line, optional text, context.
local function tileWidget(Kit, t, width, scale, avail_h, note)
    local TextWidget    = require("lib/bookshelf_colour_text")
    local VerticalGroup = require("ui/widget/verticalgroup")
    local VerticalSpan  = require("ui/widget/verticalspan")
    local sc = Kit.sc(scale)
    local bar
    if type(t.bar) == "number" then
        bar = Kit.progressBar{ width = width, height = sc(8), fraction = t.bar }
    end
    local card = Kit.valueCard{
        width = width, scale_pct = scale,
        heading = t.heading, value = t.value,
        suffix = t.suffix and (" " .. t.suffix) or nil,
        bar = bar, sub = t.sub,
        context = (not t.text) and t.context or nil,
    }
    if not t.text and not note then return card end

    -- Lines under the text are kept whole; the text gives way when the card is small.
    local tail = {}
    if t.text and t.context then
        tail[#tail + 1] = TextWidget:new{ text = t.context, face = Kit.face(13, scale, { italic = true }),
            fgcolor = Kit.COLOR_PRIMARY, max_width = width }
    end
    if note then
        tail[#tail + 1] = TextWidget:new{ text = note, face = Kit.face(12, scale, { italic = true }),
            fgcolor = Kit.COLOR_MUTED, max_width = width }
    end
    local g = VerticalGroup:new{ align = "left", card }
    if t.text then
        local fixed = card:getSize().h + sc(4)
        for _, w in ipairs(tail) do fixed = fixed + w:getSize().h + sc(3) end
        local max_h = (avail_h and avail_h > 0) and math.max(sc(16), avail_h - fixed) or nil
        g[#g + 1] = VerticalSpan:new{ width = sc(4) }
        g[#g + 1] = Kit.fitText{ text = t.text, size = 16, scale_pct = scale, width = width, max_h = max_h }
    end
    for _, w in ipairs(tail) do
        g[#g + 1] = VerticalSpan:new{ width = sc(3) }
        g[#g + 1] = w
    end
    return g
end

local function message(Kit, width, scale, heading, text)
    local VerticalGroup = require("ui/widget/verticalgroup")
    return VerticalGroup:new{ align = "left",
        Kit.valueCard{ width = width, scale_pct = scale, heading = heading },
        Kit.fitText{ text = text, size = 14, scale_pct = scale, width = width, fgcolor = Kit.COLOR_MUTED },
    }
end

-- Choose a screen: "What's on now" plus every screen in the saved list.
-- on_pick(name) gets nil for "what's on now".
local function chooseScreen(current, on_pick, on_cancel)
    local UIManager    = require("ui/uimanager")
    local ButtonDialog = require("ui/widget/buttondialog")
    local api = hub()
    local data = api and api.cachedList()
    local dialog
    local picked = false
    local function row(label, name)
        local mark = (current == name) and "\226\156\147 " or "   "
        return {{ text = mark .. label, align = "left", callback = function()
            picked = true
            UIManager:close(dialog)
            on_pick(name)
        end }}
    end
    local buttons = { row(_("What's on now (changes through the day)"), nil) }
    for _, s in ipairs(data and data.screens or {}) do
        buttons[#buttons + 1] = row(s.title or s.name, s.name)
    end
    dialog = ButtonDialog:new{
        title = data and _("Kindle Hub: show on this card")
            or _("Kindle Hub: show on this card\n(connect to Wi-Fi once to list every screen)"),
        title_align = "center",
        buttons = buttons,
        tap_close_callback = function()
            if not picked and on_cancel then on_cancel() end
        end,
    }
    UIManager:show(dialog)
end

local SAMPLE = {
    heading = _("Kindle Hub"),
    value = "22%", suffix = _("through Q4"), bar = 0.22,
    sub = _("Brief, weather, markets and more"),
}

return {
    key = KEY,
    title = _("Kindle Hub"),
    summary = _("Your Kindle Hub screens. Needs internet; keeps a saved copy."),
    tap_feedback = true,

    render = function(ctx)
        local Kit = require("lib/bookshelf_module_kit")
        local width, scale = math.max(50, ctx.width or 50), ctx.scale
        if ctx.preview then
            return tileWidget(Kit, SAMPLE, width, scale, ctx.height)
        end
        local api = hub()
        if not api then
            return message(Kit, width, scale, _("Kindle Hub"),
                _("Turn on the Kindle Hub plugin: Tools → More tools → Plugin management."))
        end
        if ctx.refresh then
            refreshers[(ctx.entry and ctx.entry.id or "?") .. "@" .. tostring(ctx.surface)] = ctx.refresh
        end
        local data = api.cachedList()
        maybeFetch(api, data)
        if not data then
            return message(Kit, width, scale, _("Kindle Hub"),
                _("Turn on Wi-Fi to load your screens, or tap to open Kindle Hub."))
        end
        local name = wanted(ctx)
        local screen = findScreen(data, name)
        if not screen then
            return message(Kit, width, scale, _("Kindle Hub"),
                string.format(_("\"%s\" isn't on your site any more. Long-press to pick another screen."), name))
        end
        local note
        if tonumber(data.updated_epoch) and os.time() - data.updated_epoch > OLD_DATA then
            note = string.format(_("Updated %s"), data.updated or "")
        end
        local tile = type(screen.tile) == "table" and screen.tile or { heading = screen.title }
        return tileWidget(Kit, tile, width, scale, ctx.height, note)
    end,

    on_tap = function(ctx)
        local api = hub()
        if api then api.show(wanted(ctx)) end
    end,

    on_add = function(_host, done)
        chooseScreen(false, function(name) done({ kh_screen = name }) end, function() done(nil) end)
    end,

    show_settings = function(ctx)
        if not (ctx and ctx.config) then return end
        local UIManager    = require("ui/uimanager")
        local ButtonDialog = require("ui/widget/buttondialog")
        local dialog
        dialog = ButtonDialog:new{
            title = _("Kindle Hub card"), title_align = "center",
            buttons = {
                {{ text = _("Change screen…"), callback = function()
                    UIManager:close(dialog)
                    chooseScreen(wanted(ctx), function(name)
                        if name then ctx.config:set("kh_screen", name) else ctx.config:delete("kh_screen") end
                    end)
                end }},
                {{ text = _("Refresh now"), callback = function()
                    UIManager:close(dialog)
                    local api = hub()
                    if not api then return end
                    require("ui/network/manager"):runWhenOnline(function()
                        last_try = os.time()
                        local ok, err = api.refreshList()
                        if ok then refreshCards()
                        else
                            local InfoMessage = require("ui/widget/infomessage")
                            UIManager:show(InfoMessage:new{ text = _("Kindle Hub: ") .. tostring(err), timeout = 4 })
                        end
                    end)
                end }},
            },
        }
        UIManager:show(dialog)
    end,

    -- Test hooks (Bookshelf ignores underscore keys).
    _findScreen = findScreen,
    _tileWidget = tileWidget,
    _reset = function() refreshers = {}; last_try = 0 end,
}
