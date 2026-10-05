# TechTim GCP Panel Header Standard

All game server panels use the same top-level information architecture. Game-specific artwork may change, but the layout and interaction order do not.

## Header

1. The left side is a home link containing the game-specific square mark, `TechTim {Game} Server Panel`, and `DEDICATED SERVER · GCP LINUX`.
2. The right-side actions always appear in this order: TechTim Discord, TechTim YouTube, official game guide, panel update, logout.
3. Every action uses a square game-themed image with a short Korean label below it.
4. The panel-update notification is anchored to the panel-update action.
5. Clicking the brand always returns to the overview page.

## Status Summary

The row below the header always contains four cards in this order:

1. Game
2. Install status
3. Server status
4. Panel version

Each card uses a square game-themed image, a Korean label, the primary value, and one concise supporting line. Do not duplicate the panel-update action in the sidebar or dashboard body.

## Assets And Responsive Behavior

- Navigation assets: `{game}-nav-{action}-vN.png`
- Status assets: `{game}-status-{purpose}-vN.png`
- Keep icons square and readable at 48 to 58 pixels.
- On narrow screens, preserve action order and allow the action row to scroll horizontally.
- Keep labels visible; do not replace them with unexplained glyphs.
