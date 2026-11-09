-- MARVIN's WezTerm look (marvin#1069, PRD #1058). Lives in ~/.agents, so every Mac gets the same look when it syncs.
-- Loaded from each Mac's wezterm.lua by a guarded line that `marvin_hooks.py install` adds:
--     package.path = package.path .. ';<~/.agents>/config/wezterm/?.lua'
--     pcall(function() require('marvin').apply(config) end)
-- so a broken file here leaves WezTerm on the person's own settings instead of breaking every terminal at once.
--
-- The colours come from config/palette/wezterm.json, the same file lib/contrast.py measures against the
-- accessibility rule (#1062): the terminal can't drift from what was checked. The font is MARVIN Term Mono (#1054),
-- with Menlo behind it for every glyph the draft hasn't drawn yet.
local wezterm = require 'wezterm'

local M = {}

-- WezTerm's Lua has no debug library, so find this file the way require did (the loader put its folder on the path)
local HERE = ((package.searchpath('marvin', package.path) or ''):match('(.*/)')) or './'
local AGENTS = HERE .. '../../'

local function read_palette()
  local f = io.open(AGENTS .. 'config/palette/wezterm.json', 'r')
  if not f then return nil end
  local text = f:read('*a')
  f:close()
  local ok, palette = pcall(wezterm.json_parse, text)
  if ok and type(palette) == 'table' and type(palette.terminal) == 'table' then return palette.terminal end
  return nil
end

local function glass(alpha)
  return string.format('rgba(5,4,10,%.3f)', alpha)
end

function M.colors(t, alpha)
  local g = glass(alpha)
  return {
    background = t.background, foreground = t.foreground,
    cursor_bg = t.cursor, cursor_fg = t.background, cursor_border = t.cursor,
    selection_bg = t.selection_bg, selection_fg = t.selection_fg,
    ansi = t.ansi, brights = t.brights,
    tab_bar = {
      background = g,
      active_tab = { bg_color = t.tab_active_bg, fg_color = t.tab_active_fg },
      inactive_tab = { bg_color = g, fg_color = t.tab_inactive_fg },
      inactive_tab_hover = { bg_color = g, fg_color = t.foreground },
      new_tab = { bg_color = g, fg_color = t.tab_inactive_fg },
    },
  }
end

function M.apply(config)
  local t = read_palette()
  if t then
    config.colors = M.colors(t, t.glass_focused or 0.6)
    config.window_background_opacity = t.glass_focused or 0.6
    config.macos_window_background_blur = t.blur or 24
  end

  local dirs = config.font_dirs or {}
  table.insert(dirs, AGENTS .. 'design/fonts')
  config.font_dirs = dirs
  config.font = wezterm.font_with_fallback({ 'MARVIN Term Mono', 'Menlo' })
  -- MARVIN Term is drawn on a pixel grid: 25 pt puts each font pixel on exactly two screen pixels on a Retina
  -- display, the size it was reviewed at. Other crisp sizes come with the readability keys (#1073).
  config.font_size = 25.0
  config.line_height = 1.0

  config.scrollback_lines = math.max(config.scrollback_lines or 0, 10000)

  pcall(function() require('helper_tabs_marvin') end)   -- group colours for helper tabs (#753)
  return config
end

return M
