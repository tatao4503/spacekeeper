# Spacekeeper

A macOS storage cleaner that **never deletes anything**.

Most cleaners ask you to trust a number and press a big button. Spacekeeper does
the opposite: it explains why every item is a candidate, moves only what you
picked into a quarantine folder, and lets you put it all back.

[한국어 문서](README.ko.md) · [사용설명서 (USER_GUIDE)](USER_GUIDE.html)

![Spacekeeper dashboard](docs/screenshots/dashboard.png)

---

## Why another cleaner

**Nothing is destroyed.** "Cleaning" moves files to `~/.spacekeeper/quarantine/`
and records where they came from. Restore is one click. Emptying goes to the
macOS Trash, so even that step is reversible.

<img src="docs/screenshots/onboarding.png" alt="First-run explanation of the safety model" width="620">

*The app says this on first launch, before it scans anything.*

**Every item explains itself.** Each candidate carries a reason ("Cargo can
rebuild this"), a caution, and a risk level. No opaque "Junk: 12.4 GB" buckets.

**Honest numbers.** Sizes are measured from allocated blocks (`st_blocks`), not
logical size, so sparse files and cloud placeholders don't inflate the total. The
UI says up front that APFS clones may make the real gain smaller. When a scan
stops at a limit, it says so instead of implying it saw everything.

**It knows what developers actually accumulate.** `node_modules`, Rust `target`,
Xcode `DerivedData`, `.next`, package manager caches, local LLM weights. On the
author's Mac these were ~23 GB that consumer cleaners never touch.

**Local only.** No account, no telemetry, and no external network calls. The
dashboard binds only to loopback; every API request must also carry a
per-launch 256-bit token and match the local Host/Origin. Python standard
library only — no third-party runtime dependencies.

## What it finds

| | |
|---|---|
| **Overview** | Large files, old downloads, regenerable caches, build artifacts — grouped by category with a size bar per group |
| **Space tree** | Proportional treemap of what is actually using the disk |
| **System Data** | Breaks apart the blob macOS won't explain — the only screen that looks outside your home folder ([details](#system-data)) |
| **Duplicates** | Byte-identical files (SHA-256), one copy kept per group |
| **Similar photos** | Perceptual hash (dHash) finds the same photo at different sizes or compression |
| **Apps & leftovers** | Installed apps plus the support/cache/preference files they leave in `~/Library` |
| **Browser & mail caches** | Safari, Chrome, Firefox, Edge, Arc, Mail — caches only, never mail stores or site data |
| **Startup items** | Login items; disabling moves the plist to quarantine so it is reversible |
| **Quarantine** | Everything you moved, with restore and "empty to Trash" |
| **Decision helper** | For big files that are hard to judge: where it came from, when it was last opened, whether copies exist elsewhere — clues only, no verdict |
| **History** | Every scan, quarantine, restore and empty, with a chart of how reclaimable space moved over time |
| **Diagnostics** | Whether protected folders are readable and quarantine/restore actually work |

## System Data

macOS System Settings lumps everything it can't classify into one opaque
figure. Watching it climb past 100 GB with no way to see inside is the reason
this project exists — and every other screen here stays inside your home
folder, where most of that blob isn't.

This screen breaks it apart: Xcode simulator runtimes, `/Library/Application
Support`, `/private/var` swap and scratch, app containers, device symbols, iOS
backups. On the machine it was built on that came to **96 GB, half of it
outside the home folder** and previously invisible to the app.

It is strictly read-only. Each area is graded:

| Grade | Meaning |
|---|---|
| **Cleanable here** | Home folder, regenerable — the normal quarantine flow already covers it |
| **Clean it yourself** | Only a dedicated tool removes it safely. The app explains what it is and shows the official command to copy. **It never runs it.** |
| **Managed by macOS** | Swap, scratch, logs. Left alone, and explained |

Nothing outside the home folder is ever quarantined: quarantine cannot undo a
broken system, and this app's whole safety model is *reversible or not at all*.
Every area says what it is, why it grows, and what clearing it costs — the same
explain-don't-decide stance as the rest of the app.

Sizes come from allocated blocks, and the screen states plainly that they won't
exactly match Apple's figure, because the two classify differently.

## Requirements

- macOS 12 or later (Apple Silicon)
- Python 3.11+ (for running from source)

## Run from source

```bash
git clone <this-repo>
cd spacekeeper
python3 -m spacekeeper --serve      # http://127.0.0.1:8765
```

There is also a CLI that prints a read-only report:

```bash
python3 -m spacekeeper ~/Downloads
python3 -m spacekeeper ~ --duplicates
python3 -m spacekeeper ~ --plan --risk low
```

## Build the desktop app

The desktop app is Tauri v2 with the Python server bundled as a self-contained
sidecar, so the shipped `.app` needs no Python installed.

```bash
cd desktop
npm install
npm run build        # -> src-tauri/target/release/bundle/{macos,dmg}
```

The app lives in the menu bar; closing the window keeps it running, and "Quit"
from the tray stops the bundled server too.

> **Unsigned builds.** Releases are ad-hoc signed, not notarized with an Apple
> Developer ID. macOS will warn on first launch — right-click the app and choose
> **Open**, or build it yourself with the commands above.

## Full Disk Access

Desktop, Documents and Downloads are protected by macOS. To analyze them, add
Spacekeeper under **System Settings → Privacy & Security → Full Disk Access**.
Without it those folders are skipped and reported as permission-limited; the
rest still works.

## Safety model

1. No deletion. Selected items are moved to quarantine and logged in a manifest.
2. Restore returns an item to its exact original path.
3. Emptying quarantine moves to the macOS Trash, not `unlink`.
4. Moves are restricted to your home folder and `/Applications`. `/System`,
   `/Library`, `~/.ssh` and Keychains are refused outright.
5. Symlinks are never followed.
6. Background scheduled runs notify only by default. Auto-quarantine is off
   until explicitly confirmed and is limited to package-download and tool
   caches; project dependencies, build outputs, and simulator data are excluded.

## Known limits

This is a personal tool released in the open, and it is honest about where that
shows:

- **Apple Silicon only**, macOS 12+. There is no Intel build.
- **Not notarized.** The first launch needs right-click → Open. The path to
  fixing that is written up in [docs/NOTARIZATION.md](docs/NOTARIZATION.md);
  it needs an Apple Developer account, not more code.
- **Tested on one Mac.** Nobody has run this on hardware or a macOS version
  other than the one it was built on. If you can spare 30 minutes,
  [docs/TESTING_ON_ANOTHER_MAC.md](docs/TESTING_ON_ANOTHER_MAC.md) is a
  checklist for exactly that, and the results would be the single most useful
  thing anyone could send back.

## Development

```bash
python3 -m unittest discover -s tests
```

Contributions welcome. If you add a filesystem walker, it must skip cloud
containers (`~/Library/CloudStorage`, `~/Library/Mobile Documents`) and catch
`OSError` *during* iteration — offline placeholders otherwise stall for ~17
seconds per folder and then raise.

## License

MIT — see [LICENSE](LICENSE).
