# RESCUEGRID 3D: 5-minute video recording script

The video has two parts: the architecture slide (about 50 s), then the live app (about 4 min 10 s).
Record them as **two separate clips** and join them. The app part has two waits of 30–60 s each
while drones fly and Bedrock answers. Either talk over them or cut them in editing.

---

## Before you hit record

1. **Make sure nobody else is using http://32.195.112.28.** Everyone who opens that URL shares
   the same mission. If someone else clicks Reset or a decision button, your take is ruined. If in
   doubt, record locally instead: run `scripts\restart_backend.cmd`, then open http://127.0.0.1:8000.
   It uses the same live Bedrock.
2. Use Chrome, set the window to 1920×1080, browser zoom 100%, press **F11** for full screen,
   and hide the bookmarks bar.
3. **Do one full dry run** of section C to H below, so you know what appears when.
4. Reset for the real take: click **↻** (top right), then **OK**. Press **F5** to reload the page, then
   **wait about 30 seconds** until the terrain and photos are sharp.
5. Open the slide in a second Chrome tab:
   `docs\video\architecture_slide.png` (or the `.svg`). Press F11 on that tab too.
6. Recorder: OBS, or Windows Game Bar (**Win + Alt + R** starts and stops recording the current window).
7. Check the top bar of the app: **BEDROCK** and **S3** should be green and **LINK** green.

---

## Timeline

### A · 0:00–0:15 · Slide: the problem
**Screen:** architecture slide.
**Click:** nothing.
**Say:**
> "In September 2024 Hurricane Helene washed out roads and bridges across western North Carolina.
> In Swannanoa, NCDOT documented that flooding destroyed both approaches of the Whitson Avenue Bridge.
> RESCUEGRID 3D replays that event: drones scan the valley, Amazon Bedrock reads the imagery, a
> commander confirms what's blocked, and the system reroutes rescuers on the real road network."

### B · 0:15–0:50 · Slide: architecture and tech stack
**Screen:** same slide. If your recorder allows it, move the mouse pointer to each part as you name it.
**Say:**
> "On the left is the real public data: USGS elevation, the OpenStreetMap road graph, NOAA aerial
> photos from five days after the storm, and the NCDOT damage record.
> The browser runs a CesiumJS 3D globe with React panels. It talks to a FastAPI backend on EC2
> over REST and a live WebSocket.
> On EC2, a mission engine flies three simulated drones. Their synthetic lidar is cast against the
> real terrain and compared with the pre-storm surface to find changes.
> When something changes on a road, the drone's image goes to Amazon Bedrock: Claude Sonnet 4.5
> through the Converse API, forced to answer in a fixed JSON format. Pydantic validates the answer.
> The model never picks coordinates or roads; GIS matching does that.
> A human confirms, NetworkX reroutes on the real graph, and Bedrock writes the briefing.
> Evidence goes to S3, logs and Bedrock metrics go to CloudWatch, and the server uses a
> least-privilege IAM role with no keys on the box.
> Frontend is React, TypeScript and Cesium; backend is Python, FastAPI and NetworkX."

**Switch to the app tab now.** (Stop clip 1 and start clip 2 if recording separately.)

### C · 0:50–1:10 · App: the starting screen
**Screen:** the app in BRIEFING state. A mission card sits over the valley.
**Click:**
1. Left panel: **Documented: Whitson Ave Bridge damage (NCDOT)**. It expands.
2. Toolbar under the layer buttons: **NOAA 2024-10-05** off, then on again.

**Say:**
> "This is the command center. Everything is labelled with where it came from: historical record,
> simulated, or current basemap. This toggle is the real NOAA post-storm imagery over today's map.
> Ground teams can't reach this area, so every decision here relies on drone evidence."

### D · 1:10–2:05 · Launch the swarm
**Click:**
1. **Director** (bottom right of the 3D view).
2. **Run storyline (auto-pause at decisions)**. This launches the drones, sets 4x speed, turns on
   auto-pause and drives the camera: first a wide valley shot, then it follows Drone Bravo.
3. Click **Director** again to close its menu so it doesn't cover the view.
4. While the camera follows Bravo: click the layer buttons **Drone Scan**, then **Reconstructed Surface**.
   Leave both on.
5. Right panel: click the **Observations** tab. A **BEDROCK** spinner chip appears on an observation
   while Claude is analyzing it.

**Say:**
> "Three drones, three sectors: US 70, the river crossings, and Old US 70. Each lidar scan is cast
> against the real terrain plus the modelled storm damage. Points appear only where a drone has
> actually looked. The cyan surface is rebuilt from those points, and red marks where it differs from
> the pre-storm surface. Each drone card on the left shows battery, altitude and sector coverage.
> When the lidar sees a change on a road, the drone takes an image and sends it to Bedrock. That's
> this spinner."

### E · 2:05–2:50 · Bedrock finds the bridge damage
**What happens on its own:** about 1–1½ minutes after launch the simulation **pauses itself**.
A toast says a decision is required, and the camera flies down to the Whitson Ave bridge.
**Click:**
1. Right panel: **AI inspect** tab. The newest call is selected.
2. Scroll slowly through the card: the **LIVE AWS INFERENCE** chip, Model ID, Latency, Tokens,
   AWS request ID, the image that was sent, and the parsed JSON.

**Say:**
> "Lidar flagged the bridge approaches, and the drone's position selected the real NOAA frame from
> October fifth. This is the live Bedrock call: Claude Sonnet 4.5, [read latency] milliseconds,
> [read tokens] tokens, and this AWS request ID. The answer is structured JSON: hazard type,
> severity, confidence, what it sees and what it's unsure about. It's only advice. The road is now
> *suspected* blocked, not confirmed, and the route hasn't changed yet."

### F · 2:50–3:30 · Commander confirms, route recalculates
**Click:**
1. Right panel: **Incidents** tab, then click the bridge incident (Whitson Avenue, FLOODING / bridge).
2. Under *Drone evidence*, **tick the checkbox under each image**. Click the small checkbox,
   **not the image**; the image opens the Observations tab instead.
3. Click **Confirm blocked** (red).
4. Watch: the camera dives to the bridge, then pulls back to show the whole route (about 10 s).
   The old route turns red and dashed, and the new route glows green.
5. Point at the bottom panel, **Before / After Route**: previous 1.07 km INVALIDATED, updated 2.60 km.

**Say:**
> "I've reviewed every evidence image, so I confirm it blocked. Only a human decision does this.
> The router recalculates on the real road graph in milliseconds. The route through Whitson Avenue
> is invalid, and the new route crosses at Riverwood Road: 1.07 kilometres becomes 2.6. Amber
> segments are roads no drone has checked yet, and the coordinator has already sent a drone to the
> Riverwood bridge, because a bridge on the new route is the most valuable thing to check."

### G · 3:30–4:10 · Check the new crossing
**Click:**
1. Top bar: **Resume**.
2. Wait about 45–60 seconds for a new bridge incident at **Riverwood Road**. A toast appears and the
   Incidents tab badge goes up. *Cut this wait in editing, or talk over it.*
3. **Incidents** tab, then click the Riverwood incident. Tick each evidence checkbox, then click
   **Verify passable** (green).

**Say:**
> "The new crossing gets the same treatment: drone image, live Bedrock analysis, and my decision.
> Claude rates Riverwood as likely passable, I check the evidence, and verify it. Now the
> detour's key crossing is backed by drone evidence and a human sign-off."

### H · 4:10–4:45 · Approve and brief
**Click:**
1. Right panel: **Route & brief** tab.
2. **Approve simulated mission route**. The route turns bright green and reads *Approved by …*.
3. **Generate Bedrock mission briefing**. Click once, then wait about 15–20 s.
4. When it appears, scroll slowly through the headline, *Situation* and *Confirmed obstructions*.

**Say:**
> "I approve the route, and Bedrock writes the briefing. It only gets facts from the mission
> database and cites the incident and observation IDs. It doesn't calculate routes or invent numbers,
> and it lists what's still unverified, like the fallen trees on Old US 70."

### I · 4:45–5:00 · Close
**Click:** nothing. Optionally cut to the CloudWatch dashboard `rescuegrid3d` for 3 seconds.
**Say:**
> "Everything you saw ran live on AWS: EC2, Bedrock, S3 and CloudWatch. Travel times are
> simulated estimates, and real dispatch needs authorized people. This is RESCUEGRID 3D."

---

## Do NOT click

| Don't | Why |
|---|---|
| **↻ Reset** (top right) during the take | Wipes the mission. You'd have to restart from section C. |
| **Launch drones** / **Launch reconnaissance** | Use **Director → Run storyline** instead, which also turns on auto-pause and the camera moves. |
| **Speed buttons 1x / 4x / 10x** | The storyline sets 4x. 10x can fly past the key moments; 1x is very slow. |
| **⏭ step** button | Not needed, and it confuses the timeline. |
| Dragging or scrolling the 3D view **while the camera is moving** | It fights the Director animation. Wait until it stops. |
| The **evidence image** itself on an incident | It switches to the Observations tab. Click the **checkbox** under it. |
| **Reject** or **Re-inspect (drone)** on the bridge incident | Breaks the story. Re-inspect sends a drone back and delays everything. |
| Any decision on the **other incidents** (fallen trees on Old US 70, debris on West State St) | Leave them pending. Confirming them reroutes again. The briefing lists them as open risks, which is the right story. |
| **Generate briefing** twice | Each click is another Bedrock call. Wait the 15–20 s. |
| **Director** shots 1 / 2 / 3 or **Replay scan growth** during the storyline | They override the automatic camera. Use them only to recover a missed shot. |
| Unticking **Auto-pause when a decision is required** | The sim would run past the bridge incident. |
| Opening the app in a **second tab or device** | Same shared mission. Two viewers can cause confusion if either clicks. |

## If something goes wrong

| Problem | Fix |
|---|---|
| Top bar shows **BEDROCK** red / DEGRADED banner | The AWS credentials have probably expired. Stop and get fresh ones; the app needs a redeploy. |
| The sim pauses on a **different** incident (trees or debris) | Leave it pending and click **Resume**. Cut it in editing. |
| No bridge incident after about 2½ minutes | Check the Observations tab for a BEDROCK spinner and keep waiting. If nothing is happening, Reset and start again. |
| **Approve** is greyed out | Some segment on the route is still *suspected* blocked. Open Incidents and decide the pending incident on the route. |
| You missed the bridge camera move | **Director → 3 · Bridge dive → route reveal** replays it. |
| A messy take | **↻ Reset → OK**, **F5**, wait 30 s, and start again from section C. The slide clip doesn't need re-recording. |
