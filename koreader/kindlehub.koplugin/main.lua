--[[--
Kindle Hub screen picker for KOReader.

Lists the screens published at <site>/api/screens and shows the one you pick full screen,
the same way the TRMNL plugin shows its dashboard. Swipe left/right for the next/previous
screen, tap to close. The TRMNL dashboard's hourly schedule is left alone.
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
local USER_AGENT = "kindlehub-koreader/1.0"

local KindleHub = WidgetContainer:extend{
    name = "kindlehub",
    is_doc_only = false,
    screens = nil,      -- last list fetched from the site
    index = nil,        -- which of them is showing
    image_widget = nil,
}

function KindleHub:init()
    Dispatcher:registerAction("kindlehub_pick", {category = "none", event = "KindleHubPick",
                                                  title = _("Kindle Hub: Pick a screen"), general = true})
    self.ui.menu:registerToMainMenu(self)
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

function KindleHub:fetchList()
    local JSON = require("json")
    local socketutil = require("socketutil")
    local body = {}
    local ok, err = self:get(self:getSite() .. "/api/screens", socketutil.table_sink(body))
    if not ok then return nil, err end
    local parsed_ok, data = pcall(JSON.decode, table.concat(body))
    if not parsed_ok or type(data) ~= "table" or type(data.screens) ~= "table" or #data.screens == 0 then
        return nil, "the site has no screen list yet"
    end
    return data
end

function KindleHub:showError(msg)
    UIManager:show(InfoMessage:new{ text = _("Kindle Hub: ") .. msg, timeout = 5 })
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
        dialog = ButtonDialog:new{
            title = _("Kindle Hub") .. "\n" .. _("Updated ") .. (data.updated or ""),
            title_align = "center",
            buttons = buttons,
        }
        UIManager:show(dialog)
    end)
end

function KindleHub:showScreen(i)
    local n = #self.screens
    i = ((i - 1) % n) + 1   -- swiping past either end wraps around
    local s = self.screens[i]
    local path = DataStorage:getDataDir() .. "/cache/kindlehub-" .. s.name .. ".png"

    local file = io.open(path, "wb")
    if not file then return self:showError("can't write " .. path) end
    local socketutil = require("socketutil")
    local ok, err = self:get(s.image_url, socketutil.file_sink(file), true)
    if not ok then
        os.remove(path)
        return self:showError(s.title .. ": " .. err)
    end

    local w, h = Screen:getWidth(), Screen:getHeight()
    -- No cache: the file name is reused, and a cached bitmap would show the old picture.
    local bb = RenderImage:renderImageFile(path, false, w, h)
    if not bb then return self:showError(s.title .. ": couldn't open the image") end

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

function KindleHub:onKindleHubPick()
    self:pick()
    return true
end

function KindleHub:addToMainMenu(menu_items)
    menu_items.kindlehub = {
        text = _("Kindle Hub"),
        sorting_hint = "tools",
        callback = function() self:pick() end,
    }
end

return KindleHub
