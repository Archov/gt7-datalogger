# Overlay & streaming

The overlay is a standalone, chrome-less telemetry page at **`/overlay`** designed to be
added as an **OBS Browser source**, opened in TikTok LIVE Studio, or loaded on a phone /
pit-wall tablet. Its entire configuration lives in the URL, so OBS, a phone, and a
second monitor can each load a different setup from the same server.

![Overlay strip](../screenshots/overlay.png)

## Building an overlay

Open **Admin → Overlay & dashboard builder**. Two one-click starting points:

- **OBS strip** — transparent 1920×260 bottom strip
- **Phone dashboard** — full-screen dark grid with 9 widgets

Then customize:

- **Widgets** — check/uncheck any of the 11 widgets, reorder with ↑/↓, and scale each
  one individually (75–200 %).
- **Layout** — *Strip* (horizontal, for OBS), *Stack* (vertical column), or *Grid*
  (phone dashboard).
- **Canvas size** — *Fill source*, or exact-pixel presets: 1920×1080, 1920×260 strip,
  1080×1920 (TikTok / Shorts), 720×1280, or any custom size. The overlay renders at
  exactly those pixels.
- **Appearance** — global scale, card background opacity (0 = bare floating widgets),
  edge padding, vertical alignment.
- **Page behind the widgets** — *Transparent* (OBS Browser sources with alpha), *Green
  screen* (#00FF00 — chroma-key it in apps without alpha support), or *Solid dark*
  (phones/tablets).

The **live preview** renders the real overlay at true pixel size scaled to fit, with
optional **safe-area guides** (action-safe 5 %, title-safe 10 %). Below it, ready-made
URLs for *this device* and for *other devices* (built from the server's LAN IP) with
copy/open buttons.

**Presets** — save the current setup under a name, reload it with one click, and
export/import the whole config as JSON. Presets live in the browser's local storage.

## Widgets

| Widget | Shows |
| --- | --- |
| `gear` | current gear, with suggested-gear hint |
| `speed` | speed in your units |
| `rpm` | RPM bar with a red `SHIFT` cue at ≥ 95 % of redline |
| `inputs` | throttle / brake bars |
| `times` | lap counter, best, last with Δ |
| `delta` | big Δ-to-best number, green/red |
| `position` | race position `P n/total` |
| `tires` | 2×2 color-coded tire temps |
| `fuel` | fuel % and bar (red < 15 %) |
| `strategy` | fuel laps remaining and `PIT ≤ L<n>` |
| `clock` | in-game time of day |

## Setting up OBS

1. Build your overlay and copy the *Other devices* URL.
2. In OBS: **Sources → + → Browser**, paste the URL.
3. Set the source's width/height to **the same canvas size** you picked in the builder.
4. Done — the transparent page mode gives you clean alpha compositing. If your app
   renders transparent pages as black, switch to *Green screen* and add a chroma-key
   filter for `#00FF00`.

If the stream drops, the strip/stack layouts render nothing (an empty source, not a
frozen box) until telemetry resumes.

## URL parameters

Everything the builder does is expressible by hand:

```
http://<host>:8000/overlay?w=gear:1.25,speed,rpm,times&layout=strip&size=1920x260&bg=70&align=bottom
```

| Param | Values | Default |
| --- | --- | --- |
| `w` | comma list of widget ids, each optionally `id:scale` (0.5–3) | `gear,speed,rpm,inputs,times,tires,fuel` |
| `layout` | `strip` · `stack` · `grid` | `strip` |
| `scale` | 0.5–2 global zoom | `1` |
| `bg` | card opacity 0–100 | `70` |
| `align` | `top` · `center` · `bottom` (strip/stack) | `bottom` |
| `size` | `WxH` exact pixels | fill source |
| `pad` | `XxY` edge inset px | `16x16` |
| `page` | `transparent` · `green` · `dark` | `transparent` (`dark` for grid) |
| `demo` | `1` for placeholder data | off |

## Placeholder mode

`demo=1` shows an animated fake lap **only while no real telemetry is arriving**, with a
small amber *placeholder* tag. The moment real data resumes it switches back
automatically — so it's safe to leave on: you can design your layout without driving,
and a mid-stream connection hiccup shows moving (clearly labeled) widgets instead of a
frozen overlay.
