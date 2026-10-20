--[[--
Kindle Hub for KOReader.

Shows the Kindle Hub screens published at <site>/api/screens full screen. Swipe left/right for
the next/previous screen, tap to close. The TRMNL dashboard's hourly schedule is left alone.

The dashboard ("Dashboard shows"): Quarter Progress unless changed; or what's on now (the site's
schedule); or every screen in turn, a new one each 15 minutes (screens with a time window, like
markets in trading hours, only inside it); or any one screen.

Getting there fast:
  * "Open when KOReader starts" shows the dashboard as soon as KOReader opens (default: Always;
    when KOReader starts with Bookshelf, "Only from the Kindle Hub button", which does it only
    when started from the KUAL button in koreader/kual-kindlehub, as that button leaves a flag
    file for us to find).
  * Two gesture actions: "Kindle Hub: Open dashboard" and "Kindle Hub: Pick a screen".
  * The last list and every screen are cached, so the screen appears at once, even offline, and
    is then refreshed when Wi-Fi is up.
  * While the screen is open it keeps itself up to date (every 15 minutes, and after waking).
  * Boxes a screen marks as live (the weather clock) are drawn here, every minute.
  * With the Bookshelf plugin, Bookshelf's dashboard button opens the Kindle Hub screen instead
    of Bookshelf's cards (Tools → Kindle Hub to switch back). Kindle Hub cards for Bookshelf's
    home screen are in bookshelf_card.lua; this plugin keeps a small loader for them in
    settings/bookshelf/micromodules/.
]]

local Blitbuffer = require("ffi/blitbuffer")
local ButtonDialog = require("ui/widget/buttondialog")
local DataStorage = require("datastorage")
local Device = require("device")
local Font = require("ui/font")
local Geom = require("ui/geometry")
local GestureRange = require("ui/gesturerange")
local ImageWidget = require("ui/widget/imagewidget")
local InfoMessage = require("ui/widget/infomessage")
local InputContainer = require("ui/widget/container/inputcontainer")
local LuaSettings = require("luasettings")
local NetworkMgr = require("ui/network/manager")
local RenderImage = require("ui/renderimage")
local TextWidget = require("ui/widget/textwidget")
local UIManager = require("ui/uimanager")
local WidgetContainer = require("ui/widget/container/widgetcontainer")
local Dispatcher = require("dispatcher")
local logger = require("logger")
local _ = require("gettext")
local Screen = Device.screen
local Input = Device.input

-- Used only when the TRMNL plugin has no base URL saved.
local DEFAULT_SITE = "https://thirstyrhino.github.io/kindle-hub"
local USER_AGENT = "kindlehub-koreader/1.3"
local START_KEY = "kindlehub_start_with"          -- "always" | "launcher" | "never"
local FLAG_NAME = "kindlehub.launch"               -- written by the KUAL button, in the settings dir
local DASH_KEY = "kindlehub_bookshelf_dashboard"   -- false: leave Bookshelf's dashboard alone
local SCREEN_KEY = "kindlehub_dashboard_screen"    -- a screen name, "on_air" or "rotate"
local DEFAULT_DASHBOARD = "quarter_progress"
local REFRESH_EVERY = 15 * 60   -- while open, check the site this often (it rebuilds hourly)
local ROTATE_EVERY = 15 * 60    -- "take turns": a new screen this often
local RETRY_OFFLINE = 2 * 60    -- ...or this often while Wi-Fi is off

-- Plugins are re-created every time KOReader switches between the file browser and a book;
-- this module-level flag makes "open on start" happen once per KOReader run.
local started = false

-- The saved screen list as last read for the Bookshelf card, which reads it on every redraw.
local list_memo = nil   -- { mtime =, data = }

-- This plugin's folder, absolute (KOReader loads plugins from a relative path).
local PLUGIN_DIR = (function()
    local dir = debug.getinfo(1, "S").source:match("^@(.*/)") or "./"
    if dir:sub(1, 1) ~= "/" then
        local ok, lfs = pcall(require, "libs/libkoreader-lfs")
        local cwd = ok and lfs.currentdir()
        if cwd then dir = cwd .. "/" .. dir:gsub("^%./", "") end
    end
    return dir
end)()
local CARD_FILE = PLUGIN_DIR .. "bookshelf_card.lua"
-- Inter Display Bold cut down to the clock's characters (tools/make_clock_font.py), so the
-- time drawn here matches the screens.
local CLOCK_FONT = PLUGIN_DIR .. "fonts/InterDisplay-Bold-clock.otf"

-- Bookshelf loads every .lua in this folder as a card; ours just runs CARD_FILE.
local CARD_LOADER = [=[
-- Kindle Hub card for Bookshelf. Kept up to date by the Kindle Hub plugin; the card's code
-- lives in that plugin, at the path below.
local ok, spec = pcall(dofile, %q)
if ok and type(spec) == "table" then return spec end
return {
    key = "kindlehub", title = "Kindle Hub", summary = "Needs the Kindle Hub plugin.",
    render = function(ctx)
        local Kit = require("lib/bookshelf_module_kit")
        return Kit.fitText{ text = "Kindle Hub plugin not found in koreader/plugins.", size = 14,
            scale_pct = ctx.scale, width = math.max(50, ctx.width or 50), fgcolor = Kit.COLOR_MUTED }
    end,
}
]=]

local KindleHub = WidgetContainer:extend{
    name = "kindlehub",
    is_doc_only = false,
    screens = nil,      -- last list fetched from the site
    index = nil,        -- which of them is showing
    image_widget = nil,
}

local function exists(path)
    local f = io.open(path, "rb")
    if f then f:close() return true end
    return false
end

local function cacheDir()
    return DataStorage:getDataDir() .. "/cache"
end

local function listCachePath()
    return cacheDir() .. "/kindlehub-screens.json"
end

function KindleHub:init()
    Dispatcher:registerAction("kindlehub_now", {category = "none", event = "KindleHubNow",
                                                 title = _("Kindle Hub: Open dashboard"), general = true})
    Dispatcher:registerAction("kindlehub_pick", {category = "none", event = "KindleHubPick",
                                                  title = _("Kindle Hub: Pick a screen"), general = true})
    self.ui.menu:registerToMainMenu(self)
    package.loaded["kindlehub/api"].plugin = self
    if not started then
        started = true
        pcall(self.installCard, self)
        pcall(self.hookBookshelfDashboard, self)
        if self:shouldOpenOnStart() then
            -- Let KOReader finish drawing its first screen, then cover it.
            UIManager:nextTick(function() self:openDashboard() end)
        end
    end
end

function KindleHub:startMode()
    local saved = G_reader_settings:readSetting(START_KEY)
    if saved then return saved end
    -- KOReader set to start with Bookshelf: the shelf is home, Kindle Hub is its dashboard
    -- (and still opens from the Kindle Hub button in KUAL).
    if G_reader_settings:readSetting("start_with") == "bookshelf" then return "launcher" end
    return "always"
end

-- What the dashboard shows: a screen name, "on_air" (the site's schedule) or "rotate".
function KindleHub:dashboardChoice()
    return G_reader_settings:readSetting(SCREEN_KEY) or DEFAULT_DASHBOARD
end

-- Open the dashboard as chosen under Dashboard shows.
function KindleHub:openDashboard()
    local choice = self:dashboardChoice()
    if choice == "on_air" then
        self:showNow(nil)
    elseif choice == "rotate" then
        self:showNow(nil)
        self.rotate = true
    else
        self:showNow(choice, true)      -- that screen; what's on now if the site dropped it
    end
end

function KindleHub:shouldOpenOnStart()
    local flag = DataStorage:getSettingsDir() .. "/" .. FLAG_NAME
    local from_button = exists(flag)
    if from_button then os.remove(flag) end
    local mode = self:startMode()
    return mode == "always" or (mode == "launcher" and from_button)
end

-- Same site as the TRMNL dashboard, so there's one address to change.
function KindleHub:getSite()
    local trmnl = LuaSettings:open(DataStorage:getSettingsDir() .. "/trmnl.lua")
    local s = trmnl:readSetting("settings")
    local url = (s and s.base_url ~= "https://trmnl.app" and s.base_url) or DEFAULT_SITE
    return (url:gsub("/+$", ""))
end

-- One HTTP(S) GET into a sink. Kindles have an old certificate store, hence verify = "none" (as TRMNL does).
function KindleHub:get(url, sink, file_timeouts)
    local http = require("socket.http")
    local https = require("ssl.https")
    local socketutil = require("socketutil")
    local httpx = url:match("^https://") and https or http
    if file_timeouts then
        socketutil:set_timeout(socketutil.FILE_BLOCK_TIMEOUT, socketutil.FILE_TOTAL_TIMEOUT)
    else
        socketutil:set_timeout(socketutil.LARGE_BLOCK_TIMEOUT, socketutil.LARGE_TOTAL_TIMEOUT)
    end
    local ok, code = httpx.request{
        url = url,
        method = "GET",
        headers = { ["User-Agent"] = USER_AGENT },
        sink = sink,
        protocol = "any",
        options = { "all", "no_sslv2", "no_sslv3" },
        verify = "none",
    }
    socketutil:reset_timeout()
    if ok ~= 1 then
        return false, "can't reach the site (" .. tostring(code) .. ")"
    end
    if code ~= 200 then
        return false, "the site returned HTTP " .. tostring(code)
    end
    return true
end

local function decodeList(text)
    local JSON = require("json")
    local ok, data = pcall(JSON.decode, text or "")
    if not ok or type(data) ~= "table" or type(data.screens) ~= "table" or #data.screens == 0 then
        return nil
    end
    return data
end

-- The list from the site, saved for next time; or the saved one when the site can't be reached.
function KindleHub:fetchList()
    local socketutil = require("socketutil")
    local body = {}
    local list_cache = listCachePath()
    local ok, err = self:get(self:getSite() .. "/api/screens", socketutil.table_sink(body))
    local data = ok and decodeList(table.concat(body))
    if data then
        local f = io.open(list_cache, "wb")
        if f then f:write(table.concat(body)) f:close() end
        list_memo = nil
        return data
    end
    local cached = self:cachedList()
    if cached then
        cached.offline = true
        return cached
    end
    return nil, ok and "the site has no screen list yet" or err
end

function KindleHub:cachedList()
    local f = io.open(listCachePath(), "rb")
    if not f then return nil end
    local text = f:read("*a")
    f:close()
    return decodeList(text)
end

function KindleHub:showError(msg)
    UIManager:show(InfoMessage:new{ text = _("Kindle Hub: ") .. msg, timeout = 5 })
end

local function indexOf(data, name)
    for i, s in ipairs(data.screens) do
        if s.name == name then return i end
    end
    return nil
end

-- Screen `name`, or the one on now when name is nil (or, with fallback, when name is gone).
local function pickIndex(data, name, fallback)
    if name then
        local i = indexOf(data, name)
        if i or not fallback then return i end
    end
    return indexOf(data, data.on_air) or 1
end

-- May screen s be shown at time t (os.date("*t"))? Screens with a window (markets: weekday
-- trading hours) only inside it. Days are ISO (1 = Monday); times "HH:MM-HH:MM", local.
local function inWindow(s, t)
    local w = s.window
    if type(w) ~= "table" then return true end
    t = t or os.date("*t")
    local iso = (t.wday + 5) % 7 + 1
    local day_ok = false
    for _, d in ipairs(w.days or {}) do
        if tonumber(d) == iso then day_ok = true end
    end
    if not day_ok then return false end
    local now = t.hour * 60 + t.min
    for _, span in ipairs(w.times or {}) do
        local h1, m1, h2, m2 = tostring(span):match("^(%d+):(%d+)%-(%d+):(%d+)$")
        if h1 then
            local a, b = tonumber(h1) * 60 + tonumber(m1), tonumber(h2) * 60 + tonumber(m2)
            if (a <= b and now >= a and now <= b) or (a > b and (now >= a or now <= b)) then
                return true
            end
        end
    end
    return false
end

-- "Take turns": the next screen after `from_name` that may be shown now.
local function nextInTurn(screens, from_name, t)
    local n, start = #screens, 0
    for i, s in ipairs(screens) do
        if s.name == from_name then start = i end
    end
    for k = 1, n do
        local i = (start + k - 1) % n + 1
        if inWindow(screens[i], t) then return i end
    end
    return nil
end

-- Screen `name` (default: the one on now): the saved copy straight away (no waiting on
-- Wi-Fi), then the fresh one once connected. With fallback, what's on now if `name` is gone.
function KindleHub:showNow(name, fallback)
    self.follow_on_air = (name == nil)    -- keep following what's on now, until a swipe
    self.rotate = false
    local cached = self:cachedList()
    local shown = nil
    local i = cached and pickIndex(cached, name, fallback)
    if i then
        self.screens = cached.screens
        if exists(self:imagePath(self.screens[i])) then
            self:display(i, self:imagePath(self.screens[i]))
            shown = self.image_widget
        end
    end
    NetworkMgr:runWhenConnected(function()
        if shown and self.image_widget ~= shown then return end   -- closed or swiped meanwhile
        local data, err = self:fetchList()
        if not data then return self:showError(err) end
        if data.offline and shown then return end   -- nothing newer than what's showing
        local j = pickIndex(data, name, fallback)
        if not j then return self:showError(tostring(name) .. _(": not on the site any more")) end
        self.screens = data.screens
        self:showScreen(j)              -- offline: the saved image, or a message saying why not
    end)
end

-- Bookshelf card: put the loader where Bookshelf looks for cards, when Bookshelf is installed.
-- Rewritten only when missing or different (say, KOReader moved). If Bookshelf already
-- looked for cards in this run, the card is registered with it directly as well.
function KindleHub:installCard()
    local lfs = require("libs/libkoreader-lfs")
    local settings = DataStorage:getSettingsDir()
    local has_bookshelf = lfs.attributes(PLUGIN_DIR .. "../bookshelf.koplugin", "mode") == "directory"
        or lfs.attributes(settings .. "/bookshelf", "mode") == "directory"
    if not has_bookshelf or not exists(CARD_FILE) then return false end
    local dir = settings .. "/bookshelf/micromodules"
    if lfs.attributes(dir, "mode") ~= "directory" then
        lfs.mkdir(settings .. "/bookshelf")
        lfs.mkdir(dir)
    end
    local path = dir .. "/kindlehub.lua"
    local want = string.format(CARD_LOADER, CARD_FILE)
    local f = io.open(path, "rb")
    local have = f and f:read("*a")
    if f then f:close() end
    if have == want then return false end
    local out = io.open(path, "wb")
    if not out then return false end
    out:write(want)
    out:close()
    local Cards = package.loaded["lib/bookshelf_start_menu_modules"]
    if type(Cards) == "table" and Cards.register then
        local ok, spec = pcall(dofile, CARD_FILE)
        if ok and type(spec) == "table" then Cards.register(spec.key, spec) end
    end
    return true
end

function KindleHub:dashboardOn()
    return G_reader_settings:readSetting(DASH_KEY) ~= false
end

-- Bookshelf's dashboard (its full-screen card view) opens the Kindle Hub screen instead.
-- Bookshelf opens it in one place, MicroFullscreen.open (footer button, gesture, from a book);
-- that is wrapped once per KOReader run. If Kindle Hub has nothing to show yet (no saved
-- screen and no Wi-Fi), or the option is off, Bookshelf's own dashboard opens as usual.
function KindleHub:hookBookshelfDashboard()
    local ok, Dash = pcall(require, "lib/bookshelf_micro_fullscreen")
    if not ok or type(Dash) ~= "table" or type(Dash.open) ~= "function" then return false end
    if Dash._kindlehub_original_open then return true end
    local original = Dash.open
    Dash._kindlehub_original_open = original
    Dash.open = function(...)
        local api = package.loaded["kindlehub/api"]
        if api and api.dashboard then
            local ok_show, shown = pcall(api.dashboard)
            if ok_show and shown then return nil end
        end
        return original(...)
    end
    return true
end

-- While the screen is open: check the site every REFRESH_EVERY seconds and swap in a newer
-- picture (what's on now, or the screen you swiped to). Nothing redraws when nothing changed.
function KindleHub:scheduleRefresh(seconds)
    if not self.refresh_task then
        self.refresh_task = function() self:refreshOpenScreen() end
    end
    UIManager:unschedule(self.refresh_task)
    UIManager:scheduleIn(seconds, self.refresh_task)
end

function KindleHub:stopRefresh()
    if self.refresh_task then UIManager:unschedule(self.refresh_task) end
end

function KindleHub:refreshOpenScreen()
    if not (self.image_widget and self.screens and self.index) then return end
    local online = NetworkMgr:isConnected()
    local current = self.screens[self.index].name
    if self.rotate then return self:nextTurn(online, current) end
    if not online then return self:scheduleRefresh(RETRY_OFFLINE) end
    local data = self:fetchList()
    if data and not data.offline and self.image_widget then
        local i = self.follow_on_air and pickIndex(data, nil) or indexOf(data, current)
        if i and data.screens[i].image_url ~= self.shown_url then
            self.screens = data.screens
            self:showScreen(i, true)    -- a failed download changes nothing; tried again next time
        end
    end
    if self.image_widget then self:scheduleRefresh(REFRESH_EVERY) end
end

-- "Take turns": move on to the next screen that may be shown now (fresh when online, else the
-- saved copy). Stays put, without redrawing, when it's the only one and nothing changed.
function KindleHub:nextTurn(online, current)
    if online then
        local data = self:fetchList()
        if data and not data.offline then self.screens = data.screens end
    end
    local i = nextInTurn(self.screens, current)
    if i then
        local s = self.screens[i]
        if s.name == current and s.image_url == self.shown_url then
            i = nil
        elseif online then
            self:showScreen(i)
        elseif exists(self:imagePath(s)) then
            self:display(i, self:imagePath(s))
        end
    end
    if self.image_widget then self:scheduleRefresh(ROTATE_EVERY) end
end

-- After the Kindle wakes up, catch up once Wi-Fi is back, and put the clock right at once.
function KindleHub:onResume()
    if not self.image_widget then return end
    self:scheduleRefresh(10)
    if self.image_widget.live_rect then
        UIManager:setDirty(self.image_widget, "ui")
        self:scheduleClock()
    end
end

-- The live clock: redraw just its box at the turn of every minute while the screen is open.
function KindleHub:scheduleClock()
    if not self.clock_task then
        self.clock_task = function()
            local w = self.image_widget
            if not (w and w.live_rect) then return end
            local rect = w.live_rect
            UIManager:setDirty(w, function() return "ui", rect end)
            self:scheduleClock()
        end
    end
    UIManager:unschedule(self.clock_task)
    UIManager:scheduleIn(60 - os.date("*t").sec + 0.2, self.clock_task)
end

function KindleHub:stopClock()
    if self.clock_task then UIManager:unschedule(self.clock_task) end
end

-- Menu → Pick a screen: fetch the list, then offer one button per screen.
function KindleHub:pick()
    NetworkMgr:runWhenConnected(function()
        local info = InfoMessage:new{ text = _("Getting screens…") }
        UIManager:show(info)
        UIManager:forceRePaint()
        local data, err = self:fetchList()
        UIManager:close(info)
        if not data then return self:showError(err) end
        self.screens = data.screens

        local dialog
        local buttons = {}
        for i, s in ipairs(self.screens) do
            local label = s.title .. (s.name == data.on_air and "  ·  on now" or "")
            table.insert(buttons, {{ text = label, align = "left", callback = function()
                UIManager:close(dialog)
                self.follow_on_air = false
                self:showScreen(i)
            end }})
        end
        local updated = data.updated or ""
        if data.offline then updated = updated .. _(" (offline copy)") end
        dialog = ButtonDialog:new{
            title = _("Kindle Hub") .. "\n" .. _("Updated ") .. updated,
            title_align = "center",
            buttons = buttons,
        }
        UIManager:show(dialog)
    end)
end

function KindleHub:imagePath(s)
    return cacheDir() .. "/kindlehub-" .. s.name .. ".png"
end

-- Download screen i to its cache file (via a temporary file, so a failed download never
-- destroys the saved copy), then show it. Falls back to the saved copy when offline, unless
-- only_if_new (background refresh), when a failed download leaves the screen as it is.
function KindleHub:showScreen(i, only_if_new)
    local n = #self.screens
    i = ((i - 1) % n) + 1   -- swiping past either end wraps around
    local s = self.screens[i]
    local path = self:imagePath(s)
    local part = path .. ".part"

    local file = io.open(part, "wb")
    local ok, err = false, "can't write " .. part
    if file then
        local socketutil = require("socketutil")
        ok, err = self:get(s.image_url, socketutil.file_sink(file), true)
        pcall(file.close, file)   -- the sink closes it on success; make sure on failure too
    end
    if ok then
        os.remove(path)
        ok = os.rename(part, path)
    else
        os.remove(part)
    end
    if not ok and only_if_new then return end
    if not ok and not exists(path) then
        return self:showError(s.title .. ": " .. (err or "download failed"))
    end
    self:display(i, path)
    if ok and self.image_widget then self.shown_url = s.image_url end
end

-- The time as the screens write it: "7:05 PM" (12h) or "19:05" (24h).
local function clockText(fmt)
    if fmt == "24h" then return os.date("%H:%M") end
    return (os.date("%I:%M"):gsub("^0", "")) .. " " .. os.date("%p")
end

-- A face `px` pixels tall (KOReader scales font sizes by screen DPI, so undo that).
local function clockFace(px)
    local size = math.max(6, math.floor(px * 1000 / Screen:scaleBySize(1000) + 0.5))
    if exists(CLOCK_FONT) then
        local ok, face = pcall(Font.getFace, Font, CLOCK_FONT, size)
        if ok and face then return face end
    end
    return Font:getFace("cfont", size)
end

-- A screen picture plus the boxes the Kindle fills in itself (the weather clock): each box is
-- painted white, then the current time drawn on the screen's own baseline.
local LiveImage = WidgetContainer:extend{ live = nil }

function LiveImage:getSize()
    return self[1]:getSize()
end

function LiveImage:paintTo(bb, x, y)
    local size = self[1]:getSize()
    self.dimen = Geom:new{ x = x, y = y, w = size.w, h = size.h }
    self[1]:paintTo(bb, x, y)
    for _, it in ipairs(self.live) do
        local tw = TextWidget:new{ text = clockText(it.format), face = clockFace(it.size),
                                   fgcolor = Blitbuffer.COLOR_BLACK }
        local tsize = tw:getSize()
        local tx = it.x
        if it.align == "right" then
            tx = it.x + it.w - tsize.w
        elseif it.align == "center" then
            tx = it.x + math.floor((it.w - tsize.w) / 2)
        end
        bb:paintRect(x + it.x, y + it.y, it.w, it.h, Blitbuffer.COLOR_WHITE)
        tw:paintTo(bb, x + tx, y + it.baseline - tw:getBaseline())
        tw:free()
    end
end

-- The screen's live boxes (only clocks so far), scaled from the site's screen size to this one.
local function liveBoxes(s, w, h)
    local out, rect = {}, nil
    for _, it in ipairs(type(s.live) == "table" and s.live or {}) do
        if it.kind == "clock" and tonumber(it.x) and tonumber(it.w) and tonumber(it.baseline) then
            local sx, sy = w / (tonumber(it.sw) or 600), h / (tonumber(it.sh) or 800)
            local box = {
                kind = "clock", format = it.format, align = it.align,
                x = math.floor(it.x * sx), y = math.floor(it.y * sy),
                w = math.ceil(it.w * sx), h = math.ceil(it.h * sy),
                baseline = math.floor(it.baseline * sy + 0.5),
                size = math.max(6, math.floor((tonumber(it.size) or 40) * sy + 0.5)),
            }
            out[#out + 1] = box
            local r = Geom:new{ x = box.x, y = box.y, w = box.w, h = box.h }
            rect = rect and rect:combine(r) or r
        end
    end
    return out, rect
end

function KindleHub:display(i, path)
    local w, h = Screen:getWidth(), Screen:getHeight()
    -- No cache: the file name is reused, and a cached bitmap would show the old picture.
    local bb = RenderImage:renderImageFile(path, false, w, h)
    if not bb then return self:showError(self.screens[i].title .. ": couldn't open the image") end

    -- Swap only after the new screen rendered, so a failed download never leaves a blank page.
    if self.image_widget then UIManager:close(self.image_widget) end
    self.index = i
    self.shown_url = nil                -- a saved copy until showScreen says it downloaded
    local picture = ImageWidget:new{
        image = bb, image_disposable = true, width = w, height = h, alpha = true,
    }
    local live, rect = liveBoxes(self.screens[i], w, h)
    if #live > 0 then picture = LiveImage:new{ picture, live = live } end
    self.image_widget = self:wrap(picture, w, h)
    self.image_widget.live_rect = rect
    UIManager:show(self.image_widget)
    UIManager:setDirty(self.image_widget, "full")
    self:scheduleRefresh(REFRESH_EVERY)
    if rect then self:scheduleClock() else self:stopClock() end
end

function KindleHub:wrap(image, w, h)
    local widget = InputContainer:new{ dimen = Geom:new{ x = 0, y = 0, w = w, h = h }, image }
    local function close()
        UIManager:close(widget)
        if self.image_widget == widget then
            self.image_widget = nil
            self:stopRefresh()
            self:stopClock()
        end
        return true
    end
    widget.onKHClose = close
    -- Swipes are often a little diagonal ("northwest"), so match on the horizontal part.
    -- Up/down swipes do nothing; only a tap closes.
    widget.onKHSwipe = function(_, _, ges)
        local dir = ges and ges.direction or ""
        if dir:find("west") then
            self.follow_on_air = false
            self:showScreen(self.index + 1)
        elseif dir:find("east") then
            self.follow_on_air = false
            self:showScreen(self.index - 1)
        end
        return true
    end
    widget.onKHKey = function(_, _, key)
        if key:match({ Input.group.PgFwd }) then
            self.follow_on_air = false
            self:showScreen(self.index + 1)
            return true
        end
        if key:match({ Input.group.PgBack }) then
            self.follow_on_air = false
            self:showScreen(self.index - 1)
            return true
        end
        return close()
    end
    if Device:isTouchDevice() then
        local function anywhere(ges)
            return { GestureRange:new{ ges = ges, range = Geom:new{ x = 0, y = 0, w = w, h = h } } }
        end
        widget.ges_events = { KHClose = anywhere("tap"), KHSwipe = anywhere("swipe") }
    end
    if Device:hasKeys() then
        widget.key_events = { KHKey = { { Input.group.Any } } }
    end
    return widget
end

function KindleHub:onKindleHubNow()
    self:openDashboard()
    return true
end

-- What the Bookshelf card (bookshelf_card.lua) uses. Lives in package.loaded so the card,
-- which Bookshelf loads on its own, can find it.
local API = package.loaded["kindlehub/api"] or {}
package.loaded["kindlehub/api"] = API
API.version = 1
API.cachedList = function()
    local lfs = require("libs/libkoreader-lfs")
    local t = lfs.attributes(listCachePath(), "modification")
    if not t then list_memo = nil return nil end
    if list_memo and list_memo.mtime == t then return list_memo.data end
    local data = KindleHub:cachedList()
    list_memo = data and { mtime = t, data = data } or nil
    return data
end
-- Seconds since the saved list was written, or nil when there isn't one.
API.listAge = function()
    local lfs = require("libs/libkoreader-lfs")
    local t = lfs.attributes(listCachePath(), "modification")
    return t and os.time() - t or nil
end
-- Fetch the list now (blocking); returns it, or nil and a reason.
API.refreshList = function()
    local data, err = KindleHub:fetchList()
    if data and not data.offline then return data end
    return nil, err or _("can't reach the site")
end
-- Open screen `name` full size (nil: the one on now).
API.show = function(name)
    local viewer = API.plugin or setmetatable({}, { __index = KindleHub })
    viewer:showNow(name)
end
-- Bookshelf's dashboard button: open the Kindle Hub dashboard and return true, or return
-- false to let Bookshelf open its own (option off, or nothing saved and no Wi-Fi).
API.dashboard = function()
    if not KindleHub:dashboardOn() then return false end
    local data = KindleHub:cachedList()
    local choice = KindleHub:dashboardChoice()
    local name = (choice ~= "on_air" and choice ~= "rotate") and choice or nil
    local i = data and pickIndex(data, name, true)
    local saved = i and exists(KindleHub:imagePath(data.screens[i]))
    if not saved and not NetworkMgr:isConnected() then return false end
    local viewer = API.plugin or setmetatable({}, { __index = KindleHub })
    viewer:openDashboard()
    return true
end

function KindleHub:onKindleHubPick()
    self:pick()
    return true
end

-- Menu → Dashboard shows: what's on now, take turns, or one screen (from the saved list).
function KindleHub:dashboardChoiceItems()
    local function item(text, value, separator)
        return {
            text = text, radio = true, separator = separator,
            checked_func = function() return self:dashboardChoice() == value end,
            callback = function() G_reader_settings:saveSetting(SCREEN_KEY, value) end,
        }
    end
    local items = {
        item(_("What's on now (the site's schedule)"), "on_air"),
        item(_("Take turns: a new screen every 15 minutes"), "rotate", true),
    }
    local data = self:cachedList()
    local listed = {}
    for _i, s in ipairs(data and data.screens or {}) do
        items[#items + 1] = item(s.title or s.name, s.name)
        listed[s.name] = true
    end
    for _i, name in ipairs({ DEFAULT_DASHBOARD, self:dashboardChoice() }) do
        if not listed[name] and name ~= "on_air" and name ~= "rotate" then
            items[#items + 1] = item(name == DEFAULT_DASHBOARD and _("Quarter Progress") or name, name)
            listed[name] = true
        end
    end
    return items
end

function KindleHub:addToMainMenu(menu_items)
    local function mode_item(text, value)
        return {
            text = text,
            radio = true,
            checked_func = function() return self:startMode() == value end,
            callback = function() G_reader_settings:saveSetting(START_KEY, value) end,
        }
    end
    menu_items.kindlehub = {
        text = _("Kindle Hub"),
        sorting_hint = "tools",
        sub_item_table = {
            { text = _("Open dashboard"), callback = function() self:openDashboard() end },
            { text = _("Pick a screen"), callback = function() self:pick() end, separator = true },
            {
                text = _("Dashboard shows"),
                sub_item_table_func = function() return self:dashboardChoiceItems() end,
            },
            {
                text = _("Bookshelf's dashboard shows Kindle Hub"),
                help_text = _("Bookshelf's dashboard button opens the Kindle Hub screen instead of Bookshelf's cards."),
                checked_func = function() return self:dashboardOn() end,
                callback = function() G_reader_settings:saveSetting(DASH_KEY, not self:dashboardOn()) end,
            },
            {
                text = _("Open when KOReader starts"),
                sub_item_table = {
                    mode_item(_("Always"), "always"),
                    mode_item(_("Only from the Kindle Hub button (KUAL)"), "launcher"),
                    mode_item(_("Never"), "never"),
                },
            },
        },
    }
end

return KindleHub
