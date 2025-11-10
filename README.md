# DO-NOT-FORGET Emotional Memo

[中文版README](README.zh.md)

An ultra-lightweight tool designed for people who get easily interrupted by information streams, experience noticeable energy fluctuations, yet still crave to preserve those moments of insight and emotional resonance. It doesn’t aim for comprehensive records; it helps you capture the fleeting fragments that truly shape who you are.

* During low-energy periods, subtle experiences and feelings only persist within context. Once the environment changes, the meeting ends, or you sleep on it, those emotions dissolve into vague labels, and the passion or tenderness fades.
* For individuals with ADHD or forgetfulness, traditional long-form notes have a high activation and organization barrier. Even small interruptions kill momentum; momentary motivation and clues get lost to “the next message” or “the next call.”
* We need a “low-friction + lightweight + gentle reminder” method: open-and-write, with moderate length constraints, to help extract the emotional core and quickly seal it away—turning ephemeral mind-flows into traceable emotional archives.

## What is it?

* Open-and-write: launching the app immediately gives you an input box; no need to create/rename/choose categories.
* Light constraints: default 100 characters, forcing you to condense emotional essence and suppress “write a long essay” procrastination.
* Mood selection: choose your current emotional tone from a dropdown for self-awareness and future mood-based filtering.
* Gentle reminders: minimized to system tray, periodically nudging you to “record if you feel something,” not “write a long piece.”
* Retrospectable: moments are saved in a time series so you can review your emotional landscape across different stages.
* Local-only: SQLite database, offline-capable, self-backup friendly, no account or internet dependency.

## Real usage scenarios

* The 30 seconds before your subway reaches the station: the coolness of the handrail still in your palm, and a sudden, clear sentence explaining yourself pops up—open, type, save, close.
* In the hallway after an argument: your chest still rises and falls; you don’t need a full replay, just capture “what exactly hurt me?” This one sentence is enough for future self-understanding.
* A moment of waking up at night: no energy to turn on the computer, no desire to categorize or title—just jot down “the image and that sour feeling I woke up with,” deal with it in the morning.
* Completing a small goal: not to boast about results, but record “why I feel light and grounded right now,” so revisiting it later can reproduce a “replicable motivation.”

## What to write? (Guiding prompts)

When you don’t know what to write, start with one of these:

* My body feels…
* What moves/irritates me right now is…
* If I could only record one sentence today, it would be…
* The image/sound/smell I want to preserve is…
* What I’m actually avoiding is…
* My next tiny step is…

Keep it under 100 characters, focus on “feeling + clue.”

## Sample entries (≤100 characters)

* On my way home after overtime, I suddenly felt calm: it’s not the workload I mind, but “unclear boundaries.” I’ll write the boundaries tomorrow morning.
* After talking with him, I feel warm inside: being truly listened to is like a warm light turning on in my chest, and I slowly settle down.
* After training, exhausted but grounded: muscles trembling, heart no longer rushed; I feel myself aligning with a “controllable rhythm.”
* This hour shattered by notifications: the problem isn’t lack of focus—it’s “not giving myself permission to close the door.”

## How does it work?

* Ultra-light interaction: launch-to-write with no categorization pressure; length limit (100 chars by default) forces focus on essential emotion. See `ENTRY_CHARACTER_LIMIT` and input listeners in [`MemoWindow`](main.py).

* Safe archival: [`append_entry_to_journal`](main.py) writes each entry—mood, text, timestamp, and unique `id`—into the local SQLite database [`DATABASE_PATH`](main.py) (default `journal.sqlite3`). The schema is intentionally simple:

  ```sql
  CREATE TABLE moments (
      id INTEGER PRIMARY KEY,
      timestamp TEXT NOT NULL,
      mood TEXT NOT NULL,
      text TEXT NOT NULL
  );
  ```

* Gentle reminders: window minimized to system tray; periodic nudges (`GENTLE_REMINDER_INTERVAL_MS`, default 1000ms example value, adjustable) help sustain “record this moment” awareness.

* Local SQLite file: no account, no network; reduces loss and leakage risk.

* The entry point [`main`](main.py) manages the app lifecycle; tray logic and minimization behavior are handled by internal methods in `MemoWindow`.

## Design trade-offs

* Only keep “text + time,” intentionally without tags/folders: lowers organization cost and preserves zero-barrier usage.
* Intentional length limit: not anti-productivity, but serves capturing the core; long-form writing can happen later during review.
* Gentle reminders instead of interruptions: reminders exist to awaken self-awareness, not to force writing.

## How to use?

### Installation

```bash
# Requires Python >=3.13
pip install pyside6
python main.py
```

On Windows:

```bash
py -3.13 -m pip install pyside6
py -3.13 main.py
```

### Steps

1. After launching, choose your mood from the “Mood” dropdown.
2. In the input box, condense the source of your feeling, body sensation, or sudden motivation.
3. Watch the character counter in the corner; stay concise (the limit helps extract the emotional core).
4. Click “Archive to Journal” to immediately save to `journal.sqlite3`.
5. Closing the window moves it to the system tray, where gentle reminders continue; click the tray icon to restore when needed.

## FAQ

* What if I want to write more?
  Save the “core one sentence” first; expand it into a long text later during review.
* How to adjust the 100-character limit?
  Modify `ENTRY_CHARACTER_LIMIT` in `main.py`, then restart.
* Reminders too frequent/too sparse?
  Adjust `GENTLE_REMINDER_INTERVAL_MS` (milliseconds) in `main.py`.
* Where is the data stored?
  By default in `journal.sqlite3` (see `DATABASE_PATH`). Back it up manually or sync it via your preferred method.
* Can I customize mood choices?
  Modify the `MOOD_CHOICES` list in `main.py`; you can change both displayed labels and stored values.
* Multi-device sync?
  No built-in cloud sync. Use your own cloud drive or version control for syncing the SQLite file.

## Privacy & data

* Data is stored locally in a lightweight SQLite database, easy to back up, migrate, or analyze (e.g., query directly or export to CSV).
* No collection, no upload—your emotions belong to you.

## Review & reflection (optional)

Weekly or monthly, pick a fixed time to scroll through `journal.sqlite3` (or exported views) and answer three questions:

* Which moments carry the most energy? What common factors do they share?
* Which recurring “pain points” signal the need for boundaries or adjustments?
* What do I want to keep or let go of in the next stage?

Link the short lines together, and you’ll see a personal emotional contour map.

## License

MIT. See [LICENSE](LICENSE).

---

Keep recording. Build your “map of emotional time,” and prevent forgetting the moments that shape you.
