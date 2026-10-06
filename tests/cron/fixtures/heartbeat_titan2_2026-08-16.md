# Heartbeat Tasks

<!--
This file is checked periodically by your Jafta agent. When the gateway starts with `gateway.heartbeat.enabled=true`, it automatically registers a protected heartbeat cron job that reads this file.

If this file has no tasks (only headers and comments), the agent will skip it. Completed tasks should be deleted, not kept — heartbeat only reads "Active Tasks".
-->

## Active Tasks

<!-- Add your periodic tasks below this line -->

### RainCheck: allerta pioggia nelle città
- Ogni ciclo, segui la skill `raincheck` per leggere la probabilità di pioggia in tutte le città.
- Avverti l'utente SOLO se almeno una città ha pioggia **> 70%**. Se tutto è ≤70%, non dire nulla.
- Anti-spam: notifica una sola volta per città per evento sopra soglia; non ripetere finché quella città non torna ≤70%, oppure se resti sopra soglia da oltre 6 ore.
- Se pibox/Tailscale è irraggiungibile: salta il ciclo in silenzio, nessun avviso (riproverai al prossimo ciclo).

