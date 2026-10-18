# Ghost Typer

A macOS menu bar app that types text from your clipboard with realistic human-like behavior. It simulates natural typing patterns including mistakes, corrections, pauses, fatigue, and variable speed — powered by AI-generated typing profiles.

## Features

- **Realistic typing simulation** — bimodal keystroke timing, finger-specific speeds, hand alternation effects
- **AI-powered planning** — Claude generates unique typing profiles and behavioral patterns for each session
- **Natural mistakes** — typos, corrections, word rewrites, and abandoned words that mimic real human behavior
- **Fatigue modeling** — typing gradually slows and error rates increase over time
- **Rich text support** — handles bold, italic, underline, and other formatting via hotkeys
- **Table fill mode** — batch-type multiple cells with Tab navigation
- **Progress overlay** — floating timer shows estimated time remaining
- **Menu bar controls** — pause, resume, cancel, and configure from the menu bar
- **Hotkeys** — F6 to pause, Shift+F6 to stop, Ctrl+F6 to toggle on/off

## Setup

### Requirements

- macOS 12+
- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/) (for AI features)

### Install

```bash
git clone https://github.com/gavinzdarko/ghost-typer.git
cd ghost-typer
pip3 install -r requirements.txt
```

Alternatively, install the package with `pip3 install .` and run `ghost-typer`.
OCR dependencies are optional: `pip3 install '.[verification]'` (also requires
the Tesseract executable). Development checks use `pip3 install '.[dev]'`.

### Configure API Key

You have three options (checked in this order):

1. **Settings UI** — click the menu bar icon > Settings > Anthropic API Key. The masked field starts blank; Save replaces the saved key, and saving blank clears it so the environment key is used. Cancel keeps the current key.
2. **`.env` file** — create a `.env` file in the project root:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
3. **Environment variable** — export it in your shell:
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   ```

### Run

```bash
python3 run.py
```

The ghost icon appears in your menu bar. Click it and select **Turn ON**.

### Usage

1. Turn ON Ghost Typer from the menu bar
2. Copy any text to your clipboard
3. Click where you want to type
4. Press **Cmd+V** — Ghost Typer intercepts the paste and types it out naturally

### Build as App (optional)

To create a standalone `Ghost Typer.app`:

```bash
pip3 install pyinstaller
bash build.sh
cp -r "dist/Ghost Typer.app" /Applications/
```

## Settings

Configurable from the menu bar:

| Setting | Default | Description |
|---------|---------|-------------|
| WPM | 65 | Base typing speed |
| Error Rate | 4% | How often typos occur |
| Start Delay | 3.0s | Delay before typing begins |
| Pause Frequency | 8% | How often natural pauses happen |
| Fatigue | On | Gradual slowdown over time |
| Burst Typing | On | Speed variation within words |
| AI Planning | On | AI-generated typing profiles |
| Sound | On | Notification sounds |
| Verify After Typing (OCR) | Off | Verify output with the optional OCR dependencies |
| Anthropic API Key | Empty | Replace or clear the saved key with masked native input |
| Notification Webhook | Empty | Replace or clear the HTTP/HTTPS notification destination |

## License

MIT
