# Set it as your launcher

Jafta can optionally replace your phone's home screen, but you don't have to use it that way — everything else about the app works identically whether or not you do.

## Why this exists

Jafta's manifest declares the `HOME`, `LAUNCHER`, and `DEFAULT` intent categories on its main activity, the same categories a real launcher app declares. That's a deliberate choice, not an accident: the idea is presence. An assistant you have to remember to open is easy to forget about; one that's simply *there* when you press Home is not. If the agent is going to message you proactively and act on a schedule anyway, being the first thing you see reinforces that instead of competing with it.

It is also what makes the "dedicated device" use case work: a spare Android phone, sitting on a desk, permanently plugged in, that boots straight into the agent instead of an app drawer nobody opens.

## Setting it as your launcher

1. Install Jafta (see [Install the APK](install.md)) and complete onboarding.
2. Press the Home button on your device.
3. Android detects more than one app registered to handle Home and shows you a chooser. Pick Jafta, and choose "Always" (rather than "Just once") if you want it to stick without asking again every time.

If you don't want the chooser to appear at all yet, just don't press Home after installing — Jafta only takes over the role once you actively pick it.

## Where the Home button lands

Once Jafta is your launcher, every press of Home arrives inside the app and means "you're home": whatever is open on top closes (a sheet, a mini-app, an enlarged image), you land back in your personal conversation, even if you were inside a notebook, and the chat scrolls to its latest message. The on-screen keyboard closes too; with a physical keyboard the message field keeps the focus, so you can start typing straight away. If you are in the workshop when you press Home, it closes whatever is open there and goes to the workshop's **Console**.

There is no setting for where Home lands. Earlier versions had a **Home button** choice (Chat, Apps, Workspace, or "Wherever I was"); it was retired, and Home always goes back to the conversation.

Pressing Back works one layer at a time and, in the personal conversation with nothing open on top, does nothing: since Jafta is the launcher, Back never closes it.

## Reverting to your normal launcher

Android's Home-app selection is a system setting, not something Jafta controls once you've picked "Always." To change it back:

1. Open Android **Settings → Apps → Default apps → Home app** (the exact path varies a bit by Android version and manufacturer skin).
2. Select your previous launcher (Nova, the stock launcher, whatever you used before).

Uninstalling Jafta also removes it from the list of launcher candidates automatically, but you don't need to uninstall it just to stop using it as Home — you can keep the app, keep your memory and conversation, and simply launch it like a normal app from your regular home screen instead.

Used that way, Jafta sits in the app switcher like any other app, so swiping through Recents brings you back to it without going through the drawer. (Up to 0.3.0 it didn't: the activity declared `excludeFromRecents`, which earns nothing in launcher mode — the system already keeps the active home task out of Recents — and only ever applied to the case it hurt. Tapping the ongoing notification also brings you back.)

## A note on screen shape

Jafta grew up on a Unihertz Titan 2, a phone with a square 1440×1440 display and a physical keyboard, and the UI still works there: it is built mobile-first and does not assume an aspect ratio. The screenshots in this documentation come from an ordinary tall phone screen (1080×1920), which is what most people will see.

## The honest assessment: as a launcher, it's not a good one

Judged purely as a home-screen replacement, Jafta is a weak launcher. There are no widgets, no folders, no icon packs, and no wallpaper management — none of the things a dedicated launcher app is judged on. What it has instead is a search drawer, the **Apps** page beside the conversation, that lists your installed Android apps alongside Jafta's own mini-apps (see [Phone app launcher](../using/app-launcher.md) for what it can and can't do), plus a theme picker and a mascot.

The launcher role is the *how*, not the *what*: it exists to make the agent the thing you land on, not to compete with Nova or Niagara on features. If you want both — Jafta's presence and a fully-featured launcher — treat this as an either/or per device rather than expecting Jafta to cover both jobs on your primary phone.

## Related pages

- [Phone app launcher](../using/app-launcher.md) — the drawer that opens your apps, and the card (a long press) where you uninstall an Android app or pin a mini-app as a page
- [Install the APK](install.md) — permissions declared, including why there's no `CAMERA` or storage permission
- [Introduction](introduction.md) — the "daily launcher vs. dedicated device" framing in full
