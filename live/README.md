# /live — live edge bot

Alerts a human when a prop line drifts far enough from the projection to clear the publish bar, pre-game (adaptive
polling) and in-game (ESPN state + in-game model). It never places a bet. Full doc: `docs/LIVE.md`.

```
pip install -e pipeline -e live
python -m live status              # budget + context, no credits
python -m live pregame --once      # one polling tick
python -m live worker              # hosted entrypoint (pre-game watcher + in-game tracker + CLV closer)
python -m live replay --season 2025
python -m live report --days 7
cd live && pytest
```
