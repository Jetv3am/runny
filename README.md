# Running Coach — Apple Health foundation

A local-first FastAPI project that imports running workouts and VO₂ max samples from Apple's built-in Health export. It does **not** connect to Strava, and it does not require an API subscription.

Current features:

- Import Apple's `export.zip` or the `export.xml` inside it.
- Keep running workouts only; ignore unrelated workout types.
- Extract workout date, duration, distance, calories, and heart-rate summary statistics when present.
- Import VO₂ max samples when present in the export.
- Save records to SQLite with stable IDs so re-importing the same file doesn't duplicate rows.
- Calculate a simple fitness profile from recent history.
- Interactive API documentation at `/docs`.
- Optional direct sync from a native iOS companion app using HealthKit background delivery.

This is the data foundation, not yet an AI coach or a personalized training prescription.

## 1. Set up

Requires Python 3.10+.

```bash
cd running-coach
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env            # optional; defaults work locally
```

No Strava credentials or external API keys are needed.

## 2. Export Apple Health data

On your iPhone:

1. Open **Health**.
2. Tap your profile picture or initials.
3. Choose **Export All Health Data** and confirm.
4. Transfer the resulting ZIP to your computer (for example, using AirDrop) or save it in Files and move it to your project computer.

The ZIP normally contains `export.xml`. You can upload either the ZIP or that XML file. The app reads the XML as a stream and doesn't extract the entire archive to disk.

## 3. Run the app

From the project root:

```bash
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Use the upload form on the home page, or open <http://127.0.0.1:8000/docs> and try `POST /health/import`.

After importing, visit:

- <http://127.0.0.1:8000/activities> — workout rows
- <http://127.0.0.1:8000/health/metrics> — VO₂ max samples
- <http://127.0.0.1:8000/fitness/profile> — recent baseline summary
- <http://127.0.0.1:8000/fitness/profile?days=84> — an 12-week view

The first import may take a while if your export contains years of health data. Re-importing the same export is safe and updates rows with matching IDs.

## 4. Try the sample export

To test without using personal health data, upload `sample_data/apple_health_sample.xml` from the home page or API docs. It contains synthetic workouts and VO₂ max values.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health/status` | App and database counts |
| `POST` | `/health/import` | Upload `.zip` or `.xml` |
| `POST` | `/health/workouts/sync` | Authenticated batch sync from the iOS HealthKit app |
| `GET` | `/activities?limit=100` | List imported runs |
| `GET` | `/health/metrics?metric_type=vo2_max` | List imported metrics |
| `GET` | `/fitness/profile?days=28` | Calculate current fitness summary |

## 5. Optional: automatic workout sync from iPhone (HealthKit)

The export upload above is manual. To automatically ingest a new Apple Watch run after it appears in Apple Health, use the Swift starter code in `ios/RunningCoach/` and a native iOS app in Xcode. The Python server alone cannot observe the iPhone's Health database.

### Configure the backend

1. Copy `.env.example` to `.env` and set `SYNC_API_TOKEN` to a long random secret, for example from `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
2. Restart the API so it loads the environment variable.
3. For local iPhone testing, run the API on your trusted home network with `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`.
4. Find your development computer's LAN IP address and put it in `ContentView.swift` as the base URL (use `http://YOUR_COMPUTER_LAN_IP:8000`, not `127.0.0.1`). Set the same token in the Swift file.
5. Do not expose this development server to the public internet. For remote access, use HTTPS and proper per-user/device authentication instead of shipping a shared token in an app.

### Set up the iOS app in Xcode

1. Create a new iOS App using SwiftUI and add the files in `ios/RunningCoach/` to the app target.
2. Under **Signing & Capabilities**, add **HealthKit** and enable **Background Delivery**.
3. Add `NSHealthShareUsageDescription` to the app's Info settings, explaining that the app reads running workouts to build a personalized training plan. Add `NSLocalNetworkUsageDescription` for local-network development.
4. If connecting to a local HTTP development server, configure a narrow local-network App Transport Security exception for development. Prefer HTTPS for any deployed service; do not disable transport security in a production app.
5. Run the app on your physical iPhone, tap **Connect Apple Health**, and approve workout read access. Background observation should be tested on a real device, not just the Simulator.

The iOS starter listens for HealthKit workout changes with `HKObserverQuery`, retrieves added workouts using `HKAnchoredObjectQuery`, and posts running summaries to `POST /health/workouts/sync`. Set `SYNC_API_TOKEN` on the backend. The API token in the Swift sample is a personal-development placeholder, not a production authentication design.

**Timing limitation:** HealthKit supports background delivery for workouts, but iOS controls scheduling. Even with `.immediate`, delivery is not a hard real-time guarantee. If you force-quit the iOS app, background behavior can also change. The app should retry failed uploads and should re-sync when opened.

The direct-sync starter currently sends date, duration, distance, calories, and source. Heart-rate summary fields are supported by the endpoint but are left empty by the Swift sample until we add the associated HealthKit heart-rate queries.

## How the current metrics work

The first fitness profile reports running volume over the last 7 days and the prior 7 days, week-over-week volume change when a comparison week exists, total distance and run count over the selected period, average runs per week, longest run, average recorded pace, average available run heart rate, and the latest two VO₂ max samples.

Missing values stay `null`; the app doesn't make up heart-rate or VO₂ max data. The profile includes a rough data-confidence label based on the number of imported runs. It is not a medical assessment and is not enough on its own to prescribe safe training intensity.

## Privacy and upload limits

- By default the app binds to `127.0.0.1`, so it is available only on your computer.
- Imported records are stored in `running_coach.db` (or `DATABASE_PATH` in `.env`).
- The defaults limit compressed uploads to 1,024 MB and the XML entry to 2,048 MB. Adjust `MAX_UPLOAD_MB` and `MAX_XML_MB` if your own export is larger.
- Treat your export and database as sensitive health data. Do not commit them to Git or expose the API publicly. This project does not send data to an LLM or any external service.

## Project structure

```text
running-coach/
├── app/
│   ├── __init__.py
│   ├── analytics.py       # deterministic running metrics
│   ├── apple_health.py    # ZIP/XML parser
│   ├── config.py
│   ├── db.py               # SQLite persistence
│   └── main.py             # FastAPI endpoints
├── sample_data/
│   └── apple_health_sample.xml
├── tests/
│   └── test_apple_health.py
├── .env.example
├── .gitignore
└── requirements.txt
```

## Next milestones

1. Add more metrics and trend charts.
2. Add runner goals (race distance, target time, race date, available days).
3. Build rule-based training-plan generation with sensible validation.
4. Add an LLM coaching layer that explains plans and answers questions using the measured fitness profile, rather than inventing metrics.
5. Expand the native iOS/HealthKit integration to sync VO₂ max samples and heart-rate summaries, then add goal setting and rule-based plans.

## Current milestone: import diagnostics, goals, and a starter plan

The Apple Health parser has been hardened to remove each processed XML element from its immediate parent rather than clearing the entire root. Clearing the root while `iterparse` is reading ahead can detach sibling elements and cause records to be skipped. The parser also recognizes running activity variants and matches VO2 max records more tolerantly.

After replacing the old project files with this version, restart the server and upload `export.xml` again. Check the response's `running_workouts_processed`, `vo2_max_samples_processed`, and `total_workout_elements_seen` values. Existing data is kept; imports are idempotent.

### Save a goal

Use `POST /goals` in `/docs` with JSON such as:

```json
{
  "goal_type": "half_marathon",
  "target_time_seconds": 7200,
  "race_date": "2027-04-18",
  "training_days": ["Tuesday", "Thursday", "Saturday", "Sunday"]
}
```

Supported `goal_type` values: `5k`, `10k`, `half_marathon`, `marathon`. `target_time_seconds` and `race_date` are optional. The current single-user MVP stores one active goal.

### Generate a starter weekly plan

Call `GET /training/plan` after saving a goal. The plan uses the deterministic fitness profile and available training days. With fewer than three recent runs (or no recent volume), it deliberately produces an easy-run-only template. This is a foundation, not yet a race-optimized or medically individualized prescription. The next iteration should improve schedule placement, race-date progression, intensity zones, and user feedback before adding an LLM.

## Frontend dashboard

The home page is now a responsive dashboard served by FastAPI:

- `app/templates/dashboard.html` — dashboard and goal modal markup
- `app/static/dashboard.css` — responsive visual design
- `app/static/dashboard.js` — connects the UI to the existing API endpoints

Start the server with `uvicorn app.main:app --reload` and open `http://127.0.0.1:8000`. From the dashboard you can upload an Apple Health `.xml`/`.zip`, view recent activities and fitness metrics, set a race goal, and request the starter training plan. The UI intentionally flags the known parser condition where the export reports running records but zero workouts are saved; the dashboard does not fabricate activity data to make the metrics look populated.
