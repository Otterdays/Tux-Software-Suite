<div align="center">

<img src="tux-software-suite.svg" width="96" alt="Tux Software Suite logo">

# Tux Software Suite · TSS

**A Ninite-style app store for Ubuntu & Debian.**
Dev tools, AI coding agents, everyday apps and games — one click each, straight from the official source.

![Platform](https://img.shields.io/badge/platform-Ubuntu%20%7C%20Debian-E95420?logo=ubuntu&logoColor=white)
![GTK4](https://img.shields.io/badge/GTK-4-4A86CF?logo=gtk&logoColor=white)
![Python](https://img.shields.io/badge/python-3-3776AB?logo=python&logoColor=white)
![Packages](https://img.shields.io/badge/packages-228-0d9488)

<img src="docs/screenshot.webp" alt="Tux Software Suite screenshot" width="900">

</div>

## ✨ Features

- **One-click install, reinstall and uninstall** for 220+ tools, with batch **Install selected** (apt packages are merged so you type your password once) and a summary of anything that failed.
- **Installed and not installed never get mixed up**: every section is split into a green **Installed** half and a **Not installed** half, each row carries a coloured state pill (✓ installed, ⬇ version you get, ⬆ update waiting, ⇩ manual download) and installed rows are tinted green.
- **Filter chips** with live counts (All, Installed, Not installed, Updates) sit above the list, plus a summary card in the sidebar and a progress bar, so you see at a glance what this PC already has.
- **Fold sections away** with the arrow next to the heading (or **Collapse all** for a one-line overview of everything); what you folded is remembered for next time, and a search always opens everything up again.
- **Search that shows its work**: every word typed has to match, and the matches are highlighted in the list. "flatpak app" finds the Flatpak apps, not just rows with one of the words.
- **Know what a program needs first**: a row says *needs Node.js* or *needs Flatpak + Flathub* when something else is missing, and that is installed first, automatically.
- **Tick all** in a section header ticks everything that is missing there; a one-line notice tells you what just happened.
- **Quick picks** menu ticks a ready-made set (fresh install, web dev, Python & data, AI agents, systems dev, gamer, video & photo, music).
- **Dependencies handled**: picking TypeScript also installs Node.js first, Gradle pulls in SDKMAN, Flatpak apps pull in Flathub, and so on. apt lists are refreshed on a fresh system, and a missing internet connection is reported plainly.
- **Update all** upgrades every apt program marked ⬆ in one go, and a program with a newer version gets its own **Update** button.
- **Open button** launches installed apps and IDEs, and opens AI agent CLIs in a terminal.
- **Transparent**: hover any name to see its official source, the exact command it will run and how it is installed (apt, snap, flatpak, npm, .deb or script). **Copy link** and **Copy command** put either on the clipboard.
- **Live status**: installed count, installed versions, available updates, and filters by state or section. Just start typing to filter.
- **Safe uninstalls**: apt removals do a dry run first and stop if they'd take anything else with them.
- **Compact layout**: section sidebar with install counts, slim rows with a ⋮ menu, and a window that fits small laptop screens.
- **Keyboard shortcuts**: Ctrl+F search, Ctrl+R recheck, Ctrl+I install what is ticked, Ctrl+U update all. The window size, the last section and the folded sections are remembered.
- **Collapsible log** with Copy and Clear, plus a system info popover (app version, OS, kernel, session, CPU, RAM, disk, GPU).

## 📦 What's inside

| Section | Highlights |
| --- | --- |
| **Developers** | C/C++, Java 17/21/25, SDKMAN, Gradle, Kotlin, Python + uv, Rust, Node.js, fnm, TypeScript, pnpm, Bun, Deno, Go, Docker, Podman, GitHub CLI, .NET 10, PHP, Ruby |
| **Python & data** | Build headers, pyenv, Poetry, JupyterLab, Ruff, Miniforge, R |
| **More languages** | Elixir, Haskell (GHCup), Julia, Lua, OCaml, Nim, Clojure, Zig, Crystal, Racket, Ada (GNAT), Odin |
| **Build, debug & DevOps** | meson/ccache/mold, lldb/strace/heaptrack, pre-commit/tig, mise, AWS CLI, Ansible, kubectl, Helm, Minikube, Network tools (nmap + Wireshark), Podman Desktop, Dev Toolbox |
| **Databases & APIs** | SQLite, PostgreSQL, Redis, Bruno, MySQL, DBeaver, Beekeeper Studio, Postman |
| **Editors & IDEs** | VS Code, IntelliJ IDEA, Zed, Neovim + LazyVim, Micro, Emacs, VSCodium, JetBrains Toolbox, Cursor, Antigravity IDE, Trae, Qoder IDE |
| **Android** | Android Studio, Android SDK tools, adb/fastboot, scrcpy, Waydroid, Android File Transfer, Universal Android Debloater, Heimdall, apktool, jadx, Flutter |
| **AI coding agents** | Claude Code, Codex CLI, OpenCode, Devin, Qoder, MiniMax Code, Antigravity CLI, DeepSeek Harness, Gemini CLI, GitHub Copilot CLI, Amp, Cursor CLI, Aider, Verdent, Z Code, Goose, Qwen Code |
| **AI apps** | ChatGPT, Claude Desktop, T3 Code (release and nightly), Ollama, Alpaca, LM Studio, Jan, Cherry Studio, Chatbox, AnythingLLM, Speech Note, Antigravity |
| **Terminal & power tools** | Ghostty, Kitty, Alacritty, fish, ripgrep/fzf/bat/eza/zoxide, Starship, lazygit, atuin, CLI extras (gping/procs/bandwhich/sd/xh/glow/duf/just), Distrobox |
| **Everyday** | Flatpak + Flathub, VLC, LibreOffice, ONLYOFFICE, Pandoc, GIMP, GNOME Tweaks, Timeshift, Chrome, Brave, Obsidian, Zotero, Anki, Telegram, Signal, Element, Thunderbird, Zoom, Bitwarden, KeePassXC, qBittorrent, Spotify, Flatseal, Gear Lever, GParted, virt-manager, VirtualBox, GNOME Boxes, BleachBit, Stacer, Syncthing, Foliate, Zathura |
| **Creative & media** | OBS Studio, Kooha, Flameshot, mpv, ffmpeg + yt-dlp + gallery-dl, MediaInfo, MKVToolNix, HandBrake, Kdenlive, Shotcut, OpenShot, Flowblade, LosslessCut, Audacity, Ardour, LMMS, Mixxx, Hydrogen, Qtractor, Sonic Pi, MuseScore, Picards, Inkscape, Krita, Photoflare, darktable, RawTherapee, digiKam, Entangle, Synfig, Pencil2D, Pixelorama, Natron, Blender, OpenSCAD, FreeCAD, FontForge, Scribus, Calibre, Xournal++, Aegisub, Gaupol |
| **Gaming** | Steam, Lutris, Heroic, ProtonUp-Qt, GameMode + MangoHud, Discord, Prism Launcher, RetroArch, PCSX2, Wine, Bottles, Godot, DOSBox, ScummVM, SuperTuxKart, 0 A.D., Hedgewars, Battle for Wesnoth, Freeciv, OpenTTD |

Some tools (Antigravity app and IDE, JetBrains Toolbox, Cursor, LM Studio, AnythingLLM, Trae, Qoder IDE, OpenCode Desktop, Z Code) don't have a one-click scripted install here, so their **Download** button opens the official download page instead.

## 🚀 Install

Download the latest `tux-software-suite_<version>_all.deb`, double-click it and click **Install** in App Center. Then open **Tux Software Suite** from the app menu.

Or from a terminal:

```bash
sudo apt install ./tux-software-suite_1.21.0_all.deb
```

Uninstall with `sudo apt remove tux-software-suite`. It replaces the old `dev-installer` package automatically.

Works on Ubuntu, Debian and derivatives (Mint, Pop!_OS…), since the buttons use `apt`.

## 🛠 Build from source

```bash
git clone https://github.com/Otterdays/Tux-Software-Suite.git
cd Tux-Software-Suite
./build-deb.sh          # package lands in dist/
python3 tux_software_suite.py   # or run it directly (needs python3-gi, gir1.2-gtk-4.0)
```

Bump `VERSION` at the top of `tux_software_suite.py` for new releases; the build and the in-app version block both read it.
