--[[--
Kindle Hub for KOReader.

Shows the Kindle Hub screens published at <site>/api/screens full screen. Swipe left/right for
the next/previous screen, tap to close. The TRMNL dashboard's hourly schedule is left alone.

Getting there fast:
  * "Open when KOReader starts" (default: Always) shows the current screen as soon as KOReader
    opens. "Only from the Kindle Hub button" does it only when started from the KUAL button in
    koreader/kual-kindlehub (that button leaves a flag file for us to find).
  * Two gesture actions: "Kindle Hub: Show current screen" and "Kindle Hub: Pick a screen".
  * The last list and every screen are cached, so the screen appears at once, even offline, and
    is then refreshed when Wi-Fi is up.
]]

local ButtonDialog = require("ui/widget/buttondialog")
local DataStorage = require("datastorage")
local Device = require("device")
local Geom = require("ui/geometry")
local GestureRange = require("ui/gesturerange")
local ImageWidget = require("ui/widget/imagewidget")
local InfoMessage = require("ui/widget/infomessage")
local InputContainer = require("ui/widget/container/inputcontainer")
local LuaSettings = require("luasettings")
local NetworkMgr = require("ui/network/manager")
local RenderImage = require("ui/renderimage")
local UIManager = require("ui/uimanager")
local WidgetContainer = require("ui/widget/container/widgetcontainer")
local Dispatcher = require("dispatcher")
local logger = require("logger")
local _ = require("gettext")
local Screen = Device.screen
local Input = Device.input

-- Used only when the TRMNL plugin has no base URL saved.
local DEFAULT_SITE = "https://thirstyrhino.github.io/kindle-hub"
local USER_AGENT = "kindlehub-koreader/1.1"
local START_KEY = "kindlehub_start_with"          -- "always" | "launcher" | "never"
local FLAG_NAME = "kindlehub.launch"               -- written by the KUAL button, in the settings dir

-- Plugins are re-created every time KOReader switches between the file browser and a book;
-- this module-level flag makes "open on start" happen once per KOReader run.
local started = false

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

function KindleHub:init()
    Dispatcher:registerAction("kindlehub_now", {category = "none", event = "KindleHubNow",
                                                 title = _("Kindle Hub: Show current screen"), general = true})
    Dispatcher:registerAction("kindlehub_pick", {category = "none", event = "KindleHubPick",
                                                  title = _("Kindle Hub: Pick a screen"), general = true})
    self.ui.menu:registerToMainMenu(self)
    if not started then
        started = true
        if self:shouldOpenOnStart() then
            -- Let KOReader finish drawing its first screen, then cover it.
            UIManager:nextTick(function() self:showNow() end)
        end
    end
end

function KindleHub:startMode()
    return G_reader_settings:readSetting(START_KEY) or "always"
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
    local list_cache = cacheDir() .. "/kindlehub-screens.json"
    local ok, err = self:get(self:getSite() .. "/api/screens", socketutil.table_sink(body))
    local data = ok and decodeList(table.concat(body))
    if data then
        local f = io.open(list_cache, "wb")
        if f then f:write(table.concat(body)) f:close() end
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
    local f = io.open(cacheDir() .. "/kindlehub-screens.json", "rb")
    if not f then return nil end
    local text = f:read("*a")
    f:close()
    return decodeList(text)
end

function KindleHub:showError(msg)
    UIManager:show(InfoMessage:new{ text = _("Kindle Hub: ") .. msg, timeout = 5 })
end

local function onAirIndex(data)
    for i, s in ipairs(data.screens) do
        if s.name == data.on_air then return i end
    end
    return 1
end

-- The screen that's on now: the saved copy straight away (no waiting on Wi-Fi), then the
-- fresh one once connected.
function KindleHub:showNow()
    local cached = self:cachedList()
    local shown = nil
    if cached then
        self.screens = cached.screens
        local i = onAirIndex(cached)
        if exists(self:imagePath(self.screens[i])) then
            self:display(i, self:imagePath(self.screens[i]))
            shown = self.image_widget
        end
    end
    NetworkMgr:runWhenConnected(function()
        if shown and self.image_widget ~= shown then return end   -- closed or swiped meanwhile
        local data, err = self:fetchList()
        if not data then return self:showError(err) end
        if data.offline then return end         -- nothing newer than what's showing
        self.screens = data.screens
        self:showScreen(onAirIndex(data))
    end)
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
-- destroys the saved copy), then show it. Falls back to the saved copy when offline.
function KindleHub:showScreen(i)
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
    if not ok and not exists(path) then
        return self:showError(s.title .. ": " .. (err or "download failed"))
    end
    self:display(i, path)
end

function KindleHub:display(i, path)
    local w, h = Screen:getWidth(), Screen:getHeight()
    -- No cache: the file name is reused, and a cached bitmap would show the old picture.
    local bb = RenderImage:renderImageFile(path, false, w, h)
    if not bb then return self:showError(self.screens[i].title .. ": couldn't open the image") end

    -- Swap only after the new screen rendered, so a failed download never leaves a blank page.
    if self.image_widget then UIManager:close(self.image_widget) end
    self.index = i
    self.image_widget = self:wrap(ImageWidget:new{
        image = bb, image_disposable = true, width = w, height = h, alpha = true,
    }, w, h)
    UIManager:show(self.image_widget)
    UIManager:setDirty(self.image_widget, "full")
end

function KindleHub:wrap(image, w, h)
    local widget = InputContainer:new{ dimen = Geom:new{ x = 0, y = 0, w = w, h = h }, image }
    local function close()
        UIManager:close(widget)
        if self.image_widget == widget then self.image_widget = nil end
        return true
    end
    widget.onKHClose = close
    -- Swipes are often a little diagonal ("northwest"), so match on the horizontal part.
    -- Up/down swipes do nothing; only a tap closes.
    widget.onKHSwipe = function(_, _, ges)
        local dir = ges and ges.direction or ""
        if dir:find("west") then
            self:showScreen(self.index + 1)
        elseif dir:find("east") then
            self:showScreen(self.index - 1)
        end
        return true
    end
    widget.onKHKey = function(_, _, key)
        if key:match({ Input.group.PgFwd }) then self:showScreen(self.index + 1) return true end
        if key:match({ Input.group.PgBack }) then self:showScreen(self.index - 1) return true end
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
    self:showNow()
    return true
end

function KindleHub:onKindleHubPick()
    self:pick()
    return true
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
            { text = _("Show current screen"), callback = function() self:showNow() end },
            { text = _("Pick a screen"), callback = function() self:pick() end, separator = true },
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
