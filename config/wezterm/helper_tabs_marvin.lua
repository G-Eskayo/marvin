-- Helper tabs (marvin#753): a tab titled "<mark> <group> · <work>" by helper-tab gets its group's colour, so a
-- window full of helpers reads as groups. Other tabs keep WezTerm's default look. Loaded from wezterm.lua by
-- `helper-tab --install-wezterm`; lives in ~/.agents so every machine gets the same colours.
local wezterm = require 'wezterm'

-- Tokyo Night accents, readable on the dark tab bar
local palette = { '#7aa2f7', '#9ece6a', '#e0af68', '#bb9af7', '#7dcfff', '#f7768e', '#ff9e64', '#73daca' }

local function group_colour(group)
  local h = 0
  for i = 1, #group do h = (h * 31 + group:byte(i)) % 2147483647 end
  return palette[(h % #palette) + 1]
end

wezterm.on('format-tab-title', function(tab, _, _, _, _, max_width)
  local title = tab.tab_title
  local group = title and title:match('^[●✓✗] (.-) · ')
  if not group then return nil end
  local colour = group_colour(group)
  local text = wezterm.truncate_right(' ' .. title .. ' ', max_width)
  if tab.is_active then
    return { { Background = { Color = colour } }, { Foreground = { Color = '#1a1b26' } }, { Text = text } }
  end
  return { { Foreground = { Color = colour } }, { Text = text } }
end)
