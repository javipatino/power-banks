# Power bank fleet connectivity dashboard

Weekly dashboard showing which Yango power bank stations were well-connected,
flaky, or dark for a given week, with a link into the fleetroom for each one.

- **Live site:** `docs/index.html`, served via GitHub Pages
- **Pipeline:** `scripts/generate_dashboard.py` reads the weekly CSV export and
  writes `docs/data/latest.json`, which the page fetches
- **Automation:** a GitHub Action regenerates the data whenever a new CSV lands
  in `data/`

## How the numbers are calculated

- **Warehouse stations excluded.** Anything with `PlaceName == "@Bogota office"`
  is inventory, not a deployment, and is dropped entirely. Edit
  `WAREHOUSE_PLACENAMES` in `scripts/generate_dashboard.py` if other
  warehouse/staging locations show up later.
- **Week window.** Monday 00:00 to Sunday 23:59, America/Bogota time. By
  default the script uses the most recently *completed* week. Pass
  `--week-start YYYY-MM-DD` to backfill a specific week instead.
- **Connectivity %** = uptime hours / hours the station could have been up
  that week, from its `Disconnections` event history. Stations created partway
  through the week get a prorated denominator (from `LocationCreatedAt` to
  week end, not the full week).
- **Categories:**
  - 🔴🔴 **0% connected** — zero disconnection events ever, but live status is
    `not_responding`. No event log to confirm downtime, but the live status
    says it's dark — treat these with a bit of healthy skepticism and spot-
    check a few against Yango's own ops view periodically.
  - 🔴 **0-25% connected**
  - 🟡 **25-50% connected**
  - 🟢 **50%+ connected**
- Each station links out to its fleetroom page:
  `https://fleet.yango.com/snickers/vendings/{DisplayNumber}?park_id={ParkID}`

## One-time setup

1. **Create the repo.** On github.com, click *New repository*. Since this
   contains real commerce names/addresses, set it to **Private**.
   > Note: GitHub Pages on a *private* repo requires GitHub Pro, Team, or
   > Enterprise. On the free plan, either make the repo public, or skip Pages
   > and just open `docs/index.html` locally / host it elsewhere.

2. **Push this folder to it:**
   ```bash
   cd yango-dashboard
   git init
   git add .
   git commit -m "Initial dashboard"
   git branch -M main
   git remote add origin https://github.com/<your-org>/<your-repo>.git
   git push -u origin main
   ```

3. **Turn on GitHub Pages:**
   Repo → *Settings* → *Pages* → under "Build and deployment", set
   **Source: Deploy from a branch**, **Branch: main**, **Folder: /docs** →
   *Save*. GitHub will give you a URL like
   `https://<your-org>.github.io/<your-repo>/` within a minute or two.

4. **Confirm Actions can push back to the repo:**
   Repo → *Settings* → *Actions* → *General* → under "Workflow permissions",
   select **Read and write permissions** → *Save*. (This lets the automated
   job commit the refreshed `docs/data/latest.json` for you.)

## Every week

1. Export the latest `vendings` CSV from Yango.
2. Drop it into the `data/` folder, named however you like (e.g.
   `data/vendings_2026-08-31.csv`).
3. Commit and push:
   ```bash
   git add data/
   git commit -m "Add week of Aug 31 data"
   git push
   ```
4. That's it — the Action runs automatically, regenerates
   `docs/data/latest.json`, and the live dashboard updates within a minute or
   two of the push. No need to run the script yourself.

If you'd rather run it locally and check the output before pushing:
```bash
python3 scripts/generate_dashboard.py
open docs/index.html   # or just double-click it
```

## Repo structure

```
yango-dashboard/
├── data/                          # weekly CSV exports (add one each week)
├── docs/                          # served by GitHub Pages
│   ├── index.html                 # the dashboard page
│   └── data/
│       ├── latest.json            # what the page reads
│       ├── weeks.json             # list of weeks with data on record
│       └── history/YYYY-MM-DD.json # archived copy of every week generated
├── scripts/
│   └── generate_dashboard.py      # the pipeline
└── .github/workflows/
    └── update-dashboard.yml       # regenerates data on push to data/
```

## Known limitations / things to keep an eye on

- The "0% connected" bucket is inferred (no events + `not_responding` status),
  not directly confirmed downtime. Spot-check it occasionally.
- `LocationCreatedAt` is used as each station's "install date" for prorating
  and ordering. It's the best field available in the export, but isn't
  guaranteed perfect (~8% of stations have an event slightly before it).
- If a busy station's `Disconnections` array is capped at some max length by
  the export, very flaky stations could have older history silently dropped —
  worth periodically checking the most-eventful stations aren't hitting a
  suspiciously round number of events.
