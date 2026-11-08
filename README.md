# Tux Software Suite (TSS)

Tux Software Suite (TSS) is a Ninite-style panel for Ubuntu/Debian with one-click buttons for installing developer tools (C/C++, Java 17/21/25, SDKMAN, Gradle, Kotlin, fnm, Python, uv, Node.js, TypeScript, pnpm, Bun, Deno, Vercel CLI, Rust, Docker, VS Code, Zed, Neovim + LazyVim, IntelliJ IDEA…), Android (Android Studio, adb, scrcpy, Flutter), AI coding agents (Claude Code, Codex, Devin, Qoder, MiniMax Code, Antigravity CLI, DeepSeek Harness, Verdent), AI apps (Claude Desktop, T3 Code release and nightly), terminal power tools (Ghostty, ripgrep/fzf/bat/eza/zoxide, Starship, lazygit), everyday apps (VLC, LibreOffice, GIMP, Timeshift…) and gaming software (Steam, Lutris, Heroic, ProtonUp-Qt, MangoHud, Discord). Hover a name to see its official source and the exact command it runs; "Copy link" copies the source URL. Type in the filter box to narrow the list.

Some tools (Antigravity app and IDE, Trae, Qoder IDE, Z Code) have no stable scripted Linux install, so their **Download** button opens the official download page instead.

## Install (for users)

Download `tux-software-suite_1.14.0_all.deb` and double-click it. It opens in App Center, where you click **Install**. Then open **Tux Software Suite** from the app menu.

From a terminal:

```bash
sudo apt install ./tux-software-suite_1.14.0_all.deb
```

Uninstall with `sudo apt remove tux-software-suite`.

Works on Ubuntu, Debian and their derivatives (Mint, Pop!_OS, etc.), since the buttons use `apt`.

## Build

```bash
./build-deb.sh
```

The package lands in `dist/`. Bump `VERSION` in `build-deb.sh` for new releases.
