# Fuel & race strategy

Two related calculations power the strategy features: a **live rolling projection**
(Live view and the overlay `strategy` widget) and the **relative fuel map** (Analysis
view).

## Live strategy projection

Computed from your most recent completed laps, in **two places that must agree**:
`frontend/src/lib/strategy.ts` (`projectStrategy`) drives the dashboard widgets, and
`backend/app/processing/strategy.py` (`project_strategy`) drives the Race Engineer's
spoken fuel callouts. Same window, same outlier rule, same arithmetic — change one and
change the other, or the voice and the display will disagree about the same tank.

```
recent        = last 3 completed laps for the CURRENT CAR that consumed > 0.01 L
usable        = recent minus partial-lap outliers (consumed < 50 % of the window max)
avgFuelPerLap = mean(usable.fuel_consumed)        # L
avgLapMs      = mean(usable.time_ms)              # ms

lapsToEmpty   = current_fuel_level / avgFuelPerLap
timeToEmpty   = lapsToEmpty × avgLapMs
pitBeforeLap  = current_lap + floor(lapsToEmpty)
```

Details that matter:

- The window is the **last 3 laps**, so the projection adapts quickly to a fuel-map
  change or a different stint pace.
- Laps **survive a race restart**: a restart opens a new recording session, but the
  previous stint's laps (same car) keep feeding the projection so you have a fuel
  estimate from the first meters — important in races with aggressive fuel
  multipliers. Switching cars drops the old car's laps from the calculation.
- **Partial laps are excluded**: a pit out-lap burns a fraction of a normal lap; if a
  lap in the window consumed less than half of the window's maximum, it is dropped
  rather than allowed to inflate the projected range.
- Laps that consumed ≤ 0.01 L (fuel-consumption off, time trials) are excluded — until
  a lap actually burns fuel, no projection is shown at all rather than a misleading one.
- **Warning colors**: the laps-to-empty readout turns amber below **4 laps** and red
  below **2 laps**.

### Race-distance fuel check

When the race length is known (`total_laps > 0`), the projection also answers "will I
make the flag?":

```
needed = (total_laps − current_lap + 1) × avgFuelPerLap
```

If `needed ≤ fuel_level` you get a green **fuel OK**; otherwise a red
**`needed − fuel_level` L short** — i.e. a pit stop (or leaner fuel map) is required.

The fuel gauge itself is simply `fuel_level ÷ fuel_capacity`, styled red below **15 %**.

## The relative fuel map (Analysis)

GT7's in-car fuel map trades power for consumption. The Analysis panel models settings
**relative to the one you drove the reference lap on** (row `0` = current), using two
approximation constants calibrated against observed in-game behavior:

- consumption changes **±10 % per step**
- lap time changes **∓250 ms per step** (richer = faster)

For each setting −5…+5:

```
fuel_per_lap   = base_fuel_per_lap × (1 + 0.10 × setting)
lap_time       = base_lap_time − 250 ms × setting
laps_remaining = fuel_level ÷ fuel_per_lap
time_remaining = laps_remaining × lap_time
```

The base consumption and lap time come from the selected reference lap; the fuel level
is the **live** value when the console is connected, falling back to the lap's
end-of-lap fuel otherwise. So during a race the table answers, in real time: *"if I lean
the map two clicks, how many extra laps do I buy and what does it cost per lap?"*

!!! note "Approximation, not simulation"
    The ±10 % and 250 ms constants are deliberate approximations — real deltas vary by
    car and track. The table is meant for relative comparisons between settings, and it
    is refreshed by real consumption data every lap, so errors don't accumulate.

## Time of day

GT7 streams the in-game clock (`day_progression_ms`). It is shown live in the strategy
panel and the overlay `clock` widget — useful for endurance races with day/night
transitions — and recorded per lap (`tod_ms`), so you can see later at what in-game
time each lap was set.
