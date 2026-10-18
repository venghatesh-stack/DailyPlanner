# DailyPlanner Notes widget (Android)

A tiny Android app whose only job is a home-screen widget for **Color Notes**.
Web apps cannot add home-screen widgets on Android, so this companion app does it.

- Shows your pinned Color Notes (or the latest notes if none are pinned) in their colours.
- Tick checklist items on the widget; tap a note to open it in DailyPlanner; tap **+** for a new note.
- Refreshes every 30 minutes, after each tick, and from its refresh button. Keeps the last notes for offline.

## Install
1. On the phone, open DailyPlanner → **Color Notes** → **Widget** → *Download the app (APK)*.
   (Direct link: https://github.com/venghatesh-stack/DailyPlanner/releases/download/notes-widget/DailyPlannerNotesWidget.apk)
2. Allow installing from Chrome/Files when Android asks; Play Protect may ask you to confirm.
3. Back in Color Notes → Widget, tap **Connect widget app**. The app opens and connects itself.
   (Or paste the server address and access code shown on that page.)
4. In the app tap **Add widget to home screen**, or long-press the home screen → Widgets → *DailyPlanner Notes*.

## How it talks to the server
- `GET  /api/widget/notes?scope=pinned|all` and `POST /api/widget/notes/<id>/toggle`, with
  `Authorization: Bearer <access code>`.
- Each phone gets its own access code; the server stores only its SHA-256 hash.
  Disconnect a phone from Color Notes → Widget → Connected phones.

## Build
GitHub Actions builds it on every push that touches this folder
(`.github/workflows/notes-widget.yml`) and publishes the APK on the `notes-widget` release.
Locally: `gradle assembleRelease` (Android SDK 34, JDK 17, Gradle 8.7+).
The signing key (`app/widget.keystore`) is committed on purpose so every build installs
as an update over the previous one.
