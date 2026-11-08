#!/usr/bin/env python3
"""Tux Software Suite (TSS): a small Ninite-style panel for installing Linux software one at a time."""
import os
import re
import shutil
import platform
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

HOME = os.path.expanduser("~")
# Per-user tools (rustup, claude, zed, uv, devin, mcode, opencode), snaps and flatpaks land here, so look there too.
EXTRA_PATHS = [
    f"{HOME}/.cargo/bin",
    f"{HOME}/.local/bin",
    f"{HOME}/.minimax-code/bin",
    f"{HOME}/.opencode/bin",
    f"{HOME}/.bun/bin",
    f"{HOME}/.deno/bin",
    f"{HOME}/.local/share/fnm",
    "/snap/bin",
    "/var/lib/flatpak/exports/bin",
    f"{HOME}/.local/share/flatpak/exports/bin",
]

FLATHUB_REPO = "https://dl.flathub.org/repo/flathub.flatpakrepo"

# Prepended to installs that need another tool first, so they fail with a clear message.
NEEDS_NPM = "command -v npm >/dev/null || { echo 'Install Node.js first.'; exit 1; }; "
NEEDS_CODE = "command -v code >/dev/null || { echo 'Install VS Code first.'; exit 1; }; "
NEEDS_UV = "test -x ~/.local/bin/uv || { echo 'Install uv first.'; exit 1; }; "

SYSTEM_PYTHON = ".".join(map(str, sys.version_info[:3]))

# Short "good to know" notes shown under a program's description.
TIPS = {
    "Python tools": "Don't use 'sudo pip install' (Ubuntu blocks it). Use 'python3 -m venv .venv' per project, "
                    "or pipx for command-line apps. Never remove the system Python.",
    "uv": "'uv python install 3.12' gets any Python version without touching the system one.",
    "Latest Python (via uv)": "Run it with 'uv run python' or make a project with 'uv init'.",
    "Java 25 (OpenJDK, latest LTS)": "Several JDKs can live side by side. Pick the default with "
                                     "'sudo update-alternatives --config java'.",
    "Rust": "Open a new terminal (or run 'source ~/.cargo/env') before using cargo.",
    "Node.js": "Ubuntu's Node can lag behind. For the newest LTS use fnm: 'fnm install --lts'.",
    "Docker": "Log out and back in so 'docker' works without sudo.",
    "GitHub CLI": "Run 'gh auth login' once to connect your account.",
    "Claude Code": "Open a new terminal, then run 'claude' inside a project folder.",
    "Flatpak + Flathub": "Log out and back in so Flatpak apps show up in the app menu.",
    "Timeshift": "Take a snapshot before big upgrades; restore it if anything breaks.",
    "Steam": "Turn on Steam Play in Settings → Compatibility to run Windows games. "
             "Check how well a game runs at protondb.com.",
    "ProtonUp-Qt": "Install GE-Proton, restart Steam, then pick it per game in Properties → Compatibility.",
    "GameMode + MangoHud": "Put 'gamemoderun mangohud %command%' in a Steam game's launch options.",
    "Lutris": "Good for Battle.net, EA app and Ubisoft Connect games.",
}

SHELL_MARK = "# >>> dev-installer shell setup >>>"
SHELL_SETUP = f"""grep -qF '{SHELL_MARK}' ~/.bashrc 2>/dev/null && {{ echo 'Already in ~/.bashrc'; exit 0; }}
cat >> ~/.bashrc <<'EOF'

{SHELL_MARK}
# Ubuntu renames these two, so give them their usual names.
command -v batcat >/dev/null && alias bat=batcat
command -v fdfind >/dev/null && alias fd=fdfind
command -v eza >/dev/null && alias ls='eza --group-directories-first' && alias ll='eza -la --git'
command -v zoxide >/dev/null && eval "$(zoxide init bash)"
command -v fzf >/dev/null && eval "$(fzf --bash)"
command -v starship >/dev/null && eval "$(starship init bash)"
# <<< dev-installer shell setup <<<
EOF
echo 'Added to ~/.bashrc. Open a new terminal to use it.'"""


def apt(*pkgs):
    return "pkexec apt-get install -y " + " ".join(pkgs)


def flatpak(app_id):
    return f"flatpak install -y --noninteractive flathub {app_id}"


def t3code(nightly):
    """T3 Code .deb from the official GitHub releases (stable = latest release, nightly = latest pre-release).
    Both channels use the package name t3code, so installing one replaces the other."""
    pick = "r['prerelease']" if nightly else "not r['prerelease']"
    return (
        "u=$(curl -fsSL 'https://api.github.com/repos/pingdotgg/t3code/releases?per_page=30' | python3 -c \""
        "import json,sys; print(next(a['browser_download_url'] for r in json.load(sys.stdin) if " + pick
        + " for a in r['assets'] if a['name'].endswith('-amd64.deb')))\") && "
        "d=$(mktemp -d) && curl -fL -o \"$d/t3code.deb\" \"$u\" && pkexec apt-get install -y \"$d/t3code.deb\""
    )


CLAUDE_DESKTOP_KEY = "/usr/share/keyrings/claude-desktop-archive-keyring.asc"
CLAUDE_DESKTOP = (
    f"pkexec bash -c 'curl -fsSLo {CLAUDE_DESKTOP_KEY} https://downloads.claude.ai/claude-desktop/key.asc && "
    f"echo \"deb [arch=amd64,arm64 signed-by={CLAUDE_DESKTOP_KEY}] "
    "https://downloads.claude.ai/claude-desktop/apt/stable stable main\" "
    "> /etc/apt/sources.list.d/claude-desktop.list && "
    "apt-get update && apt-get install -y claude-desktop'"
)

# Sections of packages. Each package: name, kind, description, command that shows it's installed,
# official page (copied by "Copy link"), and the shell command that installs it.
# The check is a command name (or several separated by |); one with a space is run as a shell test.
# Commands that need root use pkexec, which shows a password prompt.
# A command of None means there's no reliable scripted Linux install, so the button opens the page.
SECTIONS = [
    ("Developers", [
        ("Essentials", "CLI", "git, git-lfs, curl, zip/unzip, build-essential (gcc/g++, make)", "git",
         "https://packages.ubuntu.com/build-essential",
         apt("git", "git-lfs", "curl", "zip", "unzip", "build-essential")),
        ("C/C++ toolchain", "Language", "clang, clangd (editor support), cmake, ninja, gdb, valgrind, pkg-config",
         "clang", "https://clang.llvm.org/",
         apt("clang", "clangd", "cmake", "ninja-build", "gdb", "valgrind", "pkg-config")),
        ("Java 25 (OpenJDK, latest LTS)", "Language", "Newest long-term Java + Maven. Switch default with "
         "'sudo update-alternatives --config java'", "ls -d /usr/lib/jvm/java-25-openjdk-* >/dev/null 2>&1",
         "https://openjdk.org/projects/jdk/25/", apt("openjdk-25-jdk", "maven")),
        ("Java 21 (OpenJDK LTS)", "Language", "Previous LTS, still the most widely used + Maven",
         "ls -d /usr/lib/jvm/java-21-openjdk-* >/dev/null 2>&1", "https://openjdk.org/", apt("openjdk-21-jdk", "maven")),
        ("Java 17 (OpenJDK LTS)", "Language", "Older LTS for older projects and mods",
         "ls -d /usr/lib/jvm/java-17-openjdk-* >/dev/null 2>&1", "https://openjdk.org/", apt("openjdk-17-jdk")),
        ("SDKMAN", "CLI", "Installs and switches any JDK (Temurin, GraalVM, Zulu…), Gradle, Maven and more",
         "test -d ~/.sdkman", "https://sdkman.io/",
         "command -v zip >/dev/null || { echo 'Install Essentials first (needs zip).'; exit 1; }; "
         "curl -s 'https://get.sdkman.io' | bash"),
        ("Gradle", "CLI", "Latest Gradle build tool, via SDKMAN (Ubuntu's own copy is years old)",
         "test -d ~/.sdkman/candidates/gradle/current", "https://gradle.org/",
         "test -s ~/.sdkman/bin/sdkman-init.sh || { echo 'Install SDKMAN first.'; exit 1; }; "
         "source ~/.sdkman/bin/sdkman-init.sh && sdk install gradle"),
        ("Kotlin", "Language", "Latest Kotlin compiler, JetBrains' official Snap", "kotlinc|kotlin",
         "https://kotlinlang.org/", "pkexec snap install kotlin --classic"),
        ("Python tools", "CLI", f"pip, venv, pipx for Ubuntu's built-in Python {SYSTEM_PYTHON}", "pipx",
         "https://pipx.pypa.io/", apt("python3-pip", "python3-venv", "pipx")),
        ("uv", "CLI", "Astral's very fast Python package and project manager", "uv",
         "https://docs.astral.sh/uv/", "curl -LsSf https://astral.sh/uv/install.sh | sh"),
        ("Latest Python (via uv)", "Language", "Newest Python release alongside the system one, managed by uv",
         "ls -d ~/.local/share/uv/python/cpython-* >/dev/null 2>&1", "https://docs.astral.sh/uv/guides/install-python/",
         NEEDS_UV + "~/.local/bin/uv python install && ~/.local/bin/uv python list --only-installed"),
        ("Rust", "Language", "rustup + cargo, from the official rustup.rs installer", "cargo",
         "https://rustup.rs/",
         "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"),
        ("Node.js", "Runtime", "node + npm + npx; needed for TypeScript, React, Vercel, Codex and more", "npm",
         "https://nodejs.org/", apt("nodejs", "npm")),
        ("fnm", "CLI", "Fast Node version manager: run 'fnm install --lts' or switch per project", "fnm",
         "https://github.com/Schniz/fnm",
         "command -v unzip >/dev/null || { echo 'Install Essentials first (needs unzip).'; exit 1; }; "
         "curl -fsSL https://fnm.vercel.app/install | bash"),
        ("TypeScript", "Language", "tsc compiler + tsx (run .ts files directly), from npm", "tsc",
         "https://www.typescriptlang.org/", NEEDS_NPM + "pkexec npm install -g typescript tsx"),
        ("pnpm", "CLI", "Faster, disk-saving alternative to npm, from npm", "pnpm",
         "https://pnpm.io/", NEEDS_NPM + "pkexec npm install -g pnpm"),
        ("Vercel CLI", "CLI", "Deploy and preview sites on Vercel (run 'vercel login' after), from npm", "vercel",
         "https://vercel.com/docs/cli", NEEDS_NPM + "pkexec npm install -g vercel"),
        ("Bun", "Runtime", "All-in-one fast JS/TS runtime and package manager, official installer", "bun",
         "https://bun.sh/", "curl -fsSL https://bun.sh/install | bash"),
        ("Deno", "Runtime", "Secure JS/TS runtime with built-in tooling, official installer", "deno",
         "https://deno.com/", "curl -fsSL https://deno.land/install.sh | sh -s -- -y"),
        ("Go", "Language", "Go compiler and tools", "go",
         "https://go.dev/", apt("golang-go")),
        ("Docker", "CLI", "Run apps in containers; adds you to the docker group (log out and in after)",
         "docker", "https://www.docker.com/",
         f"pkexec bash -c 'apt-get install -y docker.io docker-compose-v2 && "
         f"usermod -aG docker {os.environ.get('USER', '')}'"),
        ("GitHub CLI", "CLI", "gh: pull requests, issues and repos from the terminal", "gh",
         "https://cli.github.com/", apt("gh")),
    ]),
    ("Editors & IDEs", [
        ("VS Code", "IDE", "Microsoft's editor, via Snap", "code",
         "https://code.visualstudio.com/", "pkexec snap install code --classic"),
        ("IntelliJ IDEA", "IDE", "JetBrains' Java/Kotlin IDE (free tier included), official Snap", "intellij-idea",
         "https://www.jetbrains.com/idea/", "pkexec snap install intellij-idea --classic"),
        ("Zed", "IDE", "Fast modern code editor, official installer", "zed",
         "https://zed.dev/docs/linux", "curl -f https://zed.dev/install.sh | sh"),
        ("Neovim", "CLI", "Fast, extensible terminal text editor; pair it with LazyVim below", "nvim",
         "https://neovim.io/", apt("neovim")),
        ("LazyVim starter", "CLI", "Ready-made Neovim setup (plugins, LSP, file tree); needs an empty ~/.config/nvim",
         "test -d ~/.config/nvim", "https://www.lazyvim.org/",
         "command -v nvim >/dev/null || { echo 'Install Neovim first.'; exit 1; }; "
         "git clone https://github.com/LazyVim/starter ~/.config/nvim && rm -rf ~/.config/nvim/.git && "
         "echo 'Done. Run nvim and it installs plugins on first launch.'"),
        ("Antigravity IDE", "IDE", "Google's agentic IDE; tarball only, so this opens the download page",
         "antigravity", "https://antigravity.google/download?os=linux", None),
        ("Trae", "IDE", "ByteDance's AI IDE; .deb from their site, so this opens the download page",
         "trae", "https://www.trae.ai/download", None),
        ("Qoder IDE", "IDE", "Alibaba's AI IDE (Linux beta); .deb from their site, so this opens the download page",
         "qoder", "https://qoder.com/download", None),
    ]),
    ("Android", [
        ("Android Studio", "IDE", "Google's Android IDE with SDK and emulator; Snap, auto-updates", "android-studio",
         "https://developer.android.com/studio", "pkexec snap install android-studio --classic"),
        ("Platform tools (adb)", "CLI", "Latest adb + fastboot straight from Google, plus USB rules so phones connect",
         "adb", "https://developer.android.com/tools/releases/platform-tools",
         "command -v unzip >/dev/null || { echo 'Install Essentials first (needs unzip).'; exit 1; }; "
         "tmp=$(mktemp -d) && curl -fL -o \"$tmp/pt.zip\" "
         "https://dl.google.com/android/repository/platform-tools-latest-linux.zip && "
         "rm -rf ~/.local/share/platform-tools && unzip -q \"$tmp/pt.zip\" -d ~/.local/share && mkdir -p ~/.local/bin && "
         "ln -sf ~/.local/share/platform-tools/adb ~/.local/share/platform-tools/fastboot ~/.local/bin/ && "
         "pkexec apt-get install -y android-sdk-platform-tools-common"),
        ("scrcpy", "CLI", "Mirror and control an Android phone from your desktop over USB or Wi-Fi", "scrcpy",
         "https://github.com/Genymobile/scrcpy", apt("scrcpy")),
        ("Flutter", "Language", "Google's cross-platform app SDK (Android, Linux, web), official Snap", "flutter",
         "https://docs.flutter.dev/get-started/install/linux", "pkexec snap install flutter --classic"),
    ]),
    ("AI coding agents", [
        ("Claude Code", "CLI", "Anthropic's coding agent, official installer", "claude",
         "https://claude.com/product/claude-code", "curl -fsSL https://claude.ai/install.sh | bash"),
        ("Codex CLI", "CLI", "OpenAI's coding agent, from npm (install Node.js first)", "codex",
         "https://github.com/openai/codex", NEEDS_NPM + "pkexec npm install -g @openai/codex"),
        ("OpenCode", "CLI", "Open-source terminal coding agent for any model provider, official installer",
         "opencode", "https://opencode.ai/docs/", "curl -fsSL https://opencode.ai/install | bash"),
        ("OpenCode Desktop", "App", "OpenCode's desktop app (beta); .deb/.rpm/AppImage, so this opens the download page",
         "opencode-desktop|OpenCode", "https://opencode.ai/download", None),
        ("Devin CLI", "CLI", "Cognition's Devin in the terminal, official installer", "devin",
         "https://docs.devin.ai/cli", "curl -fsSL https://cli.devin.ai/install.sh | bash"),
        ("Qoder CLI", "CLI", "Alibaba's Qoder agent in the terminal, official installer", "qodercli",
         "https://docs.qoder.com/cli", "curl -fsSL https://qoder.com/install | bash"),
        ("MiniMax Code", "CLI", "MiniMax's coding agent (mcode), official installer, no sudo", "mcode",
         "https://agent.minimax.io/docs/cli/quick-start",
         "curl -fsSL https://filecdn.minimax.chat/public/install.sh | bash"),
        ("Antigravity CLI", "CLI", "Google's Antigravity agent in the terminal (agy)", "agy",
         "https://antigravity.google/", "curl -fsSL https://antigravity.google/cli/install.sh | bash"),
        ("DeepSeek Harness", "CLI", "DeepSeek's open agent harness (preview); run 'dsh web' after", "dsh",
         "https://www.deepseek.com/en/harness/", NEEDS_NPM + "pkexec npm install -g @deepseek-ai/dsh"),
        ("Verdent", "IDE", "Verdent's agent as a VS Code extension (install VS Code first)",
         "code --list-extensions 2>/dev/null | grep -qi verdentai.verdent", "https://www.verdent.ai/",
         NEEDS_CODE + "code --install-extension verdentai.verdent"),
        ("Z Code", "CLI", "Z.ai's open-source agent; no published Linux build yet, so this opens GitHub",
         "zcode", "https://github.com/zai-org/ZCode", None),
    ]),
    ("AI apps", [
        ("Claude Desktop", "App", "Anthropic's desktop app (Linux beta), from their apt repo so it updates",
         "claude-desktop", "https://code.claude.com/docs/en/desktop-linux", CLAUDE_DESKTOP),
        ("T3 Code (release)", "App", "T3 Code stable build (amd64 .deb from GitHub releases); shares a package with Nightly",
         "dpkg -s t3code", "https://github.com/pingdotgg/t3code/releases", t3code(False)),
        ("T3 Code (nightly)", "App", "T3 Code newest nightly pre-release (amd64 .deb); replaces the release build",
         "dpkg -s t3code", "https://github.com/pingdotgg/t3code/releases", t3code(True)),
        ("Antigravity", "App", "Google's Antigravity 2.0 agent app; tarball only, so this opens the download page",
         "antigravity-hub", "https://antigravity.google/download?os=linux", None),
    ]),
    ("Terminal & power tools", [
        ("Ghostty", "App", "Fast, GPU-accelerated terminal", "ghostty",
         "https://ghostty.org/", apt("ghostty")),
        ("Modern CLI pack", "CLI", "ripgrep, fd, fzf, bat, eza, zoxide, btop, tldr, jq, tmux", "rg",
         "https://github.com/BurntSushi/ripgrep",
         apt("ripgrep", "fd-find", "fzf", "bat", "eza", "zoxide", "btop", "tealdeer", "jq", "tmux")),
        ("Shell setup", "Tool", "Adds aliases (bat, fd, ls→eza) and zoxide/fzf/starship hooks to ~/.bashrc",
         f"grep -qF '{SHELL_MARK}' ~/.bashrc", "https://github.com/ajeetdsouza/zoxide", SHELL_SETUP),
        ("Starship prompt", "CLI", "Clean, informative shell prompt (git branch, language versions)", "starship",
         "https://starship.rs/", apt("starship")),
        ("lazygit", "CLI", "Terminal UI for git: stage, commit and rebase with a few keys", "lazygit",
         "https://github.com/jesseduffield/lazygit", apt("lazygit")),
    ]),
    ("Everyday", [
        ("Flatpak + Flathub", "Tool", "App store used by Heroic and ProtonUp-Qt below", "flatpak",
         "https://flathub.org/setup/Ubuntu",
         f"pkexec bash -c 'apt-get install -y flatpak && "
         f"flatpak remote-add --if-not-exists flathub {FLATHUB_REPO}'"),
        ("VLC", "App", "Plays almost any video or audio file", "vlc",
         "https://www.videolan.org/vlc/", apt("vlc")),
        ("LibreOffice", "App", "Office suite: documents, spreadsheets, slides", "libreoffice",
         "https://www.libreoffice.org/", apt("libreoffice")),
        ("GIMP", "App", "Photo and image editor", "gimp",
         "https://www.gimp.org/", apt("gimp")),
        ("GNOME Tweaks", "Tool", "Extra desktop settings: fonts, themes, startup apps", "gnome-tweaks",
         "https://gitlab.gnome.org/GNOME/gnome-tweaks", apt("gnome-tweaks")),
        ("Timeshift", "Tool", "System snapshots, so you can undo a broken update", "timeshift",
         "https://github.com/linuxmint/timeshift", apt("timeshift")),
        ("OBS Studio", "App", "Screen recording and streaming", "obs",
         "https://obsproject.com/", apt("obs-studio")),
    ]),
    ("Gaming", [
        ("Steam", "App", "Valve's game store; runs Windows games via Proton", "steam",
         "https://store.steampowered.com/about/",
         "pkexec bash -c 'add-apt-repository -y multiverse && dpkg --add-architecture i386 && "
         "apt-get update && apt-get install -y steam-installer steam-devices'"),
        ("Lutris", "App", "One library for games from GOG, Epic, emulators and more", "lutris",
         "https://lutris.net/", apt("lutris")),
        ("Heroic Games Launcher", "App", "Epic, GOG and Amazon games (needs Flathub)",
         "com.heroicgameslauncher.hgl",
         "https://flathub.org/apps/com.heroicgameslauncher.hgl", flatpak("com.heroicgameslauncher.hgl")),
        ("ProtonUp-Qt", "App", "Install Proton-GE and Wine versions (needs Flathub)",
         "net.davidotek.pupgui2",
         "https://flathub.org/apps/net.davidotek.pupgui2", flatpak("net.davidotek.pupgui2")),
        ("GameMode + MangoHud", "Tool", "Performance boost and FPS overlay", "mangohud",
         "https://github.com/flightlessmango/MangoHud", apt("gamemode", "mangohud")),
        ("Discord", "App", "Voice and text chat, official .deb from discord.com", "discord",
         "https://discord.com/download",
         "tmp=$(mktemp -d) && curl -fL -o \"$tmp/discord.deb\" "
         "'https://discord.com/api/download?platform=linux&format=deb' && "
         "pkexec apt-get install -y \"$tmp/discord.deb\""),
    ]),
]
PACKAGES = [pkg for _, pkgs in SECTIONS for pkg in pkgs]

APT_ONLY = re.compile(r"^pkexec apt-get install -y ([\w.+\- ]+)$")

# Uninstall commands that can't be worked out from the install command.
# None means there's no safe scripted removal (it would delete your config or a tool the panel needs).
UNINSTALL = {
    "Essentials": None,  # removing curl would remove this panel too
    "Java 25 (OpenJDK, latest LTS)": "pkexec apt-get remove -y openjdk-25-jdk",
    "Java 21 (OpenJDK LTS)": "pkexec apt-get remove -y openjdk-21-jdk",
    "SDKMAN": "rm -rf ~/.sdkman && echo 'Removed ~/.sdkman. Delete the SDKMAN lines from ~/.bashrc too.'",
    "Gradle": None,
    "uv": "rm -f ~/.local/bin/uv ~/.local/bin/uvx && rm -rf ~/.cache/uv ~/.local/share/uv",
    "Rust": "~/.cargo/bin/rustup self uninstall -y",
    "fnm": "rm -rf ~/.local/share/fnm && echo 'Removed. Delete the fnm lines from ~/.bashrc too.'",
    "Bun": "rm -rf ~/.bun && echo 'Removed. Delete the bun lines from ~/.bashrc too.'",
    "Deno": "rm -rf ~/.deno && echo 'Removed. Delete the deno lines from ~/.bashrc too.'",
    "Docker": "pkexec apt-get remove -y docker.io docker-compose-v2",
    "Zed": "~/.local/bin/zed --uninstall",
    "LazyVim starter": None,  # would delete ~/.config/nvim and any changes you made
    "Platform tools (adb)": "rm -rf ~/.local/share/platform-tools ~/.local/bin/adb ~/.local/bin/fastboot",
    "Latest Python (via uv)": "~/.local/bin/uv python uninstall --all",
    "Claude Code": "rm -f ~/.local/bin/claude && rm -rf ~/.local/share/claude",
    "Devin CLI": None,
    "Qoder CLI": None,
    "MiniMax Code": None,
    "Antigravity CLI": None,
    "Verdent": "code --uninstall-extension verdentai.verdent",
    "Claude Desktop": "pkexec apt-get remove -y claude-desktop",
    "T3 Code (release)": "pkexec apt-get remove -y t3code",
    "T3 Code (nightly)": "pkexec apt-get remove -y t3code",
    "Shell setup": f"sed -i '/{SHELL_MARK}/,/# <<< dev-installer shell setup <<</d' ~/.bashrc && "
                   "echo 'Removed from ~/.bashrc.'",
    "Flatpak + Flathub": "pkexec apt-get remove -y flatpak",
    "Steam": "pkexec apt-get remove -y steam-installer steam-devices",
    "Discord": "pkexec apt-get remove -y discord",
}


def guard_apt_remove(cmd):
    """apt-get remove -y also removes anything that depends on the package (even desktop
    metapackages), so do a dry run first and stop if it would remove more than was asked."""
    if not cmd or not cmd.startswith("pkexec apt-get remove -y "):
        return cmd
    pkgs = cmd.removeprefix("pkexec apt-get remove -y ").split()
    keep = " ".join(f"-e {p}" for p in pkgs)
    return (f"extra=$(apt-get -s remove {' '.join(pkgs)} | awk '/^Remv/{{print $2}}' | grep -vxF {keep}); "
            "if [ -n \"$extra\" ]; then echo \"Stopped: this would also remove: $extra\"; "
            "echo 'Remove it yourself with apt if you are sure.'; exit 1; fi; " + cmd)


def uninstall_command(pkg):
    """Shell command that removes a package, or None if it has to be removed by hand."""
    return guard_apt_remove(_uninstall_command(pkg))


def _uninstall_command(pkg):
    name, cmd = pkg[0], pkg[5]
    if name in UNINSTALL:
        return UNINSTALL[name]
    if cmd is None:
        return None
    cmd = cmd.removeprefix(NEEDS_NPM).removeprefix(NEEDS_CODE)
    if match := APT_ONLY.match(cmd):
        return "pkexec apt-get remove -y " + match.group(1)
    if match := re.fullmatch(r"pkexec snap install (\S+) --classic", cmd):
        return f"pkexec snap remove {match.group(1)}"
    if match := re.fullmatch(r"flatpak install -y --noninteractive flathub (\S+)", cmd):
        return f"flatpak uninstall -y --noninteractive {match.group(1)}"
    if match := re.fullmatch(r"pkexec npm install -g (.+)", cmd):
        return f"pkexec npm uninstall -g {match.group(1)}"
    return None


def is_installed(check):
    if " " in check:
        return subprocess.run(["bash", "-c", check], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    path = os.environ.get("PATH", "") + ":" + ":".join(EXTRA_PATHS)
    return any(shutil.which(cmd, path=path) for cmd in check.split("|"))


# The few tools that don't take --version.
VERSION_ARGS = {"go": ["version"], "javac": ["-version"]}


# Command-line tools worth opening in a terminal window; the rest (git, cargo…) do nothing on their own.
OPEN_IN_TERMINAL = {"Claude Code", "Codex CLI", "OpenCode", "Devin CLI", "Qoder CLI", "MiniMax Code",
                    "Antigravity CLI", "DeepSeek Harness", "Neovim", "lazygit"}
# Terminal emulators and the flag that makes them run a command, in order of preference.
TERMINALS = [("ghostty", "-e"), ("gnome-terminal", "--"), ("ptyxis", "-x"), ("kgx", "-e"),
             ("konsole", "-e"), ("x-terminal-emulator", "-e")]


def tool_path():
    return os.environ.get("PATH", "") + ":" + ":".join(EXTRA_PATHS)


def launch_command(pkg):
    """argv that opens an installed package: the app itself, or a terminal running the tool. None if not openable."""
    name, kind, _, check, _, cmd = pkg
    if " " in check or (kind not in ("App", "IDE") and name not in OPEN_IN_TERMINAL):
        return None
    exe = next(filter(None, (shutil.which(c, path=tool_path()) for c in check.split("|"))), None)
    if not exe:
        return None
    if kind in ("App", "IDE"):
        return [exe]
    for term, flag in TERMINALS:
        if term_exe := shutil.which(term, path=tool_path()):
            return [term_exe, flag, "bash", "-c", f'"$0"; exec bash', exe]
    return None


def installed_version(pkg):
    """Version number of an installed command-line tool, or None. Apps are skipped so no window opens."""
    name, kind, _, check, _, cmd = pkg
    if name == "Latest Python (via uv)":
        # uv keeps each Python in a folder like cpython-3.15.2-linux-x86_64-gnu.
        versions = re.findall(r"cpython-(\d+\.\d+\.\d+)",
                              " ".join(os.listdir(f"{HOME}/.local/share/uv/python"))
                              if os.path.isdir(f"{HOME}/.local/share/uv/python") else "")
        return max(versions, key=lambda v: tuple(map(int, v.split(".")))) if versions else None
    if cmd is None or kind in ("App", "Tool") or " " in check:
        return None
    path = os.environ.get("PATH", "") + ":" + ":".join(EXTRA_PATHS)
    exe = next(filter(None, (shutil.which(c, path=path) for c in check.split("|"))), None)
    if not exe:
        return None
    try:
        out = subprocess.run([exe, *VERSION_ARGS.get(check, ["--version"])], stdin=subprocess.DEVNULL,
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"\d+\.\d+(\.\d+)?", out.stdout + out.stderr)
    return match.group(0) if match else None


def output(*args, timeout=10):
    try:
        return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def short_version(text):
    """'1:3.14.7-3ubuntu1' -> '3.14.7'"""
    match = re.search(r"(?:\d+:)?(\d+(?:\.\d+)+)", text or "")
    return match.group(1) if match else None


def apt_versions(pkg_name):
    """(installed, candidate) versions from apt, either may be None."""
    policy = output("apt-cache", "policy", pkg_name)
    found = dict(re.findall(r"^\s+(Installed|Candidate): (\S+)", policy, re.M))
    return tuple(None if found.get(k) in (None, "(none)") else short_version(found[k])
                 for k in ("Installed", "Candidate"))


def available_version(pkg):
    """Version the Install button will get, 'latest' for vendor scripts, or None if unknown."""
    cmd = pkg[5]
    if cmd is None or pkg[0] == "Shell setup":
        return None
    if pkg[0] == "Python tools":
        return f"Python {SYSTEM_PYTHON}"  # otherwise this would show pip's version
    if pkg[0] == "Platform tools (adb)":
        return "latest"  # adb comes from Google's zip, apt only adds the USB rules
    if match := re.search(r"apt-get install -y (?:--\S+ )*([a-z0-9][\w.+-]*)", cmd):
        return apt_versions(match.group(1))[1]
    if match := re.search(r"snap install (\S+)", cmd):
        found = re.search(r"^\s+latest/stable:\s+(\S+)", output("snap", "info", match.group(1)), re.M)
        return short_version(found.group(1)) if found else None
    if match := re.search(r"npm install -g (\S+)", cmd):
        return short_version(output("npm", "view", match.group(1), "version")) if shutil.which("npm") else None
    if match := re.search(r"flathub (\S+)$", cmd):
        found = re.search(r"Version: (\S+)", output("flatpak", "remote-info", "flathub", match.group(1)))
        return short_version(found.group(1)) if found else None
    return "latest"


PILL_CSS = b"""
.pill {
  background: alpha(#0d9488, 0.12);
  border: 1px solid alpha(#0d9488, 0.35);
  border-radius: 999px;
  padding: 3px 12px;
}
.pill-key { color: #0d9488; font-weight: bold; font-size: smaller; }
button.filter { background: transparent; border: 1px solid alpha(#0d9488, 0.45); border-radius: 999px;
                padding: 3px 14px; box-shadow: none; }
button.filter:hover { background: alpha(#0d9488, 0.12); }
button.filter:checked { background: #0d9488; color: white; font-weight: bold; border-color: #0d9488; }
"""


def system_info():
    """(label, value) pairs describing this PC, handy for bug reports and checking game requirements."""
    os_name = platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
    session = os.environ.get("XDG_SESSION_TYPE", "?").capitalize()
    gpus = [line.split(": ", 1)[1] for line in output("lspci").splitlines()
            if re.search(r"VGA|3D controller", line)]
    gpu = "; ".join(re.sub(r"\s*\(rev \w+\)| Corporation", "", g) for g in gpus) or "unknown"
    if nvidia := output("nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader").strip():
        gpu += f" (NVIDIA driver {nvidia})"
    mem = re.search(r"MemTotal:\s+(\d+)", open("/proc/meminfo").read())
    ram = f"{round(int(mem.group(1)) / 1024 ** 2)} GB" if mem else "?"
    disk = shutil.disk_usage(HOME)
    return [("OS", os_name), ("Kernel", platform.release().split("-")[0]), ("Session", session),
            ("CPU", f"{os.cpu_count()} threads"), ("RAM", ram), ("Free", f"{disk.free // 1024 ** 3} GB"),
            ("GPU", gpu)]


class TuxSoftwareSuite(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Tux Software Suite")
        self.set_default_size(820, 780)
        self.set_icon_name("tux-software-suite")
        self.busy = False
        self.rows = []
        self.openers = {}
        self.headers = []

        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        for side in ("top", "bottom", "start", "end"):
            getattr(grid, f"set_margin_{side}")(12)
        row = 0
        for section, pkgs in SECTIONS:
            header = Gtk.Label(xalign=0)
            header.set_markup(f"<span size='x-large' foreground='#0d9488'><b>"
                              f"{GLib.markup_escape_text(section.upper())}</b></span>")
            header.set_margin_top(0 if row == 0 else 24)
            line = Gtk.Separator(margin_bottom=4)
            first = len(self.rows)
            row += 1
            for pkg in pkgs:
                self.add_row(pkg)
            self.headers.append(((header, line), self.rows[first:]))
        self.grid = grid
        self.done = {}

        self.search = Gtk.SearchEntry(placeholder_text="Filter…", hexpand=True)
        self.search.connect("search-changed", self.on_filter)
        self.install_selected = Gtk.Button(label="Install selected", sensitive=False)
        self.install_selected.add_css_class("suggested-action")
        self.install_selected.connect("clicked", self.on_install_selected)
        clear = Gtk.Button(label="Clear selection")
        clear.connect("clicked", self.on_clear_selection)
        toolbar = Gtk.Box(spacing=6)
        for side in ("top", "start", "end"):
            getattr(toolbar, f"set_margin_{side}")(12)
        for widget in (self.search, clear, self.install_selected):
            toolbar.append(widget)

        list_scroller = Gtk.ScrolledWindow(vexpand=True)
        list_scroller.set_child(grid)
        css = Gtk.CssProvider()
        css.load_from_data(PILL_CSS, -1)
        Gtk.StyleContext.add_provider_for_display(self.get_display(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.sysinfo = []
        # Packed to the left at their natural width, so they sit evenly instead of spreading out.
        self.pills = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, hexpand=True, halign=Gtk.Align.START,
                                 homogeneous=False, column_spacing=6, row_spacing=6,
                                 min_children_per_line=1, max_children_per_line=10)
        copy_info = Gtk.Button(label="Copy", valign=Gtk.Align.START,
                               tooltip_text="Copy system info, e.g. for a bug report or forum post")
        copy_info.add_css_class("flat")
        copy_info.connect("clicked", lambda _b: self.get_clipboard().set(
            "\n".join(f"{k}: {v}" for k, v in self.sysinfo)))
        info_bar = Gtk.Box(spacing=6, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        info_bar.append(self.pills)
        info_bar.append(copy_info)
        threading.Thread(target=lambda: GLib.idle_add(self.show_pills, system_info()),
                         daemon=True).start()

        # Filter buttons: one group for install state, one for section. Each group picks one at a time.
        self.updates = set()
        self.state_filter = "All"
        self.section_filter = "All"
        filters = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False,
                              column_spacing=6, row_spacing=6, max_children_per_line=30,
                              margin_start=12, margin_end=12, margin_top=8)
        for group, options in (("state", ["All", "Installed", "Not installed", "Updates"]),
                               ("section", ["All sections"] + [s for s, _ in SECTIONS])):
            first = None
            for option in options:
                btn = Gtk.ToggleButton(label=("✓ " if first is None else "") + option, active=first is None)
                btn.add_css_class("filter")
                if first:
                    btn.set_group(first)
                else:
                    first = btn
                btn.connect("toggled", self.on_filter_button, group, option)
                filters.append(btn)
            if group == "state":
                filters.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        top.append(toolbar)
        top.append(filters)
        top.append(list_scroller)

        self.log = Gtk.TextView(editable=False, monospace=True, cursor_visible=False,
                                left_margin=12, right_margin=12, top_margin=6, bottom_margin=6)
        log_scroller = Gtk.ScrolledWindow(vexpand=True)
        log_scroller.set_child(self.log)
        log_bar = Gtk.Box(spacing=6)
        self.log_toggle = Gtk.ToggleButton(label="▾ Log", active=True, halign=Gtk.Align.START, hexpand=True,
                                           margin_start=6, tooltip_text="Hide or show the log")
        self.log_toggle.add_css_class("flat")
        self.log_toggle.connect("toggled", self.on_log_toggle)
        log_bar.append(self.log_toggle)
        self.log_scroller = log_scroller
        for label, handler in (("Recheck", lambda _b: self.refresh()),
                               ("Copy log", self.on_copy_log), ("Clear log", self.on_clear_log)):
            btn = Gtk.Button(label=label)
            btn.add_css_class("flat")
            btn.connect("clicked", handler)
            log_bar.append(btn)
        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bottom.append(log_bar)
        bottom.append(log_scroller)
        bottom.append(info_bar)

        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        paned.set_start_child(top)
        paned.set_end_child(bottom)
        paned.set_shrink_end_child(False)
        paned.set_position(560)
        self.paned = paned
        self.log_position = 560
        self.set_child(paned)
        self.refresh()

    def add_row(self, pkg):
        name, kind, desc, _check, url, cmd = pkg
        # Hovering the name or the copy button shows where it comes from and what will run.
        tooltip = f"Source: {url}\nRuns: {cmd}" if cmd else f"Source: {url}\nOpens the download page"
        tip = TIPS.get(name)
        if tip:
            tooltip += f"\nTip: {tip}"

        label = Gtk.Label(xalign=0, hexpand=True, wrap=True, tooltip_text=tooltip)
        markup = (f"<b>{GLib.markup_escape_text(name)}</b>  "
                  f"<span size='small' foreground='#0d9488'><b>[{kind}]</b></span>\n"
                  f"<small>{GLib.markup_escape_text(desc)}</small>")
        if tip:
            markup += f"\n<small><i>💡 {GLib.markup_escape_text(tip)}</i></small>"
        label.set_markup(markup)
        status = Gtk.Label(width_chars=12)
        copy = Gtk.Button(label="Copy link", tooltip_text=tooltip)
        copy.connect("clicked", self.on_copy, name, url)
        button = Gtk.Button(label="Install")
        button.connect("clicked", self.on_install, pkg)
        remove_cmd = uninstall_command(pkg)
        remove = Gtk.Button(label="Uninstall", visible=False, tooltip_text=f"Runs: {remove_cmd}")
        remove.add_css_class("destructive-action")
        remove.connect("clicked", self.on_uninstall, name, remove_cmd)
        opener = Gtk.Button(label="Open", visible=False, tooltip_text="Launch it")
        opener.add_css_class("suggested-action")
        opener.connect("clicked", self.on_open, pkg)
        self.openers[name] = opener
        actions = Gtk.Box(spacing=6)
        actions.append(opener)
        actions.append(button)
        actions.append(remove)
        # Download-only entries can't be batch installed, so they get no checkbox.
        check = Gtk.CheckButton(valign=Gtk.Align.CENTER, sensitive=cmd is not None,
                                tooltip_text="Select for Install selected")
        check.connect("toggled", lambda _c: self.update_selection())

        self.rows.append((pkg, status, button, (check, label, status, copy, actions), check, remove))

    def layout(self):
        """Lay out each section with installed tools first, then the rest, each part A–Z."""
        for child in list(self.grid):
            self.grid.remove(child)
        y = 0
        for (header, line), rows in self.headers:
            self.grid.attach(header, 0, y, 5, 1)
            self.grid.attach(line, 0, y + 1, 5, 1)
            y += 2
            for _, _, _, widgets, _, _ in sorted(rows, key=lambda r: (not self.done[r[0][0]], r[0][0].lower())):
                for col, widget in enumerate(widgets):
                    self.grid.attach(widget, col, y, 1, 1)
                y += 1

    def refresh(self):
        for pkg, status, button, _, check, remove in self.rows:
            done = self.done[pkg[0]] = is_installed(pkg[3])
            if pkg[5] is None:
                status.set_text("Installed ✓" if done else "Manual")
                button.set_label("Download")
            else:
                status.set_text("Installed ✓" if done else "Not installed")
                button.set_label("Reinstall" if done else "Install")
            button.set_sensitive(not self.busy)
            remove.set_visible(done and uninstall_command(pkg) is not None)
            self.openers[pkg[0]].set_visible(done and launch_command(pkg) is not None)
            remove.set_sensitive(not self.busy)
            check.set_sensitive(pkg[5] is not None and not self.busy)
        self.update_selection()
        self.layout()
        self.apply_filter()
        # Asking each tool for its version is slow, so do it off the UI thread.
        threading.Thread(target=self.load_versions, daemon=True).start()

    def load_versions(self):
        """Show the installed version, or the version Install will get, and flag apt updates."""
        # Each lookup can take seconds (snap and npm ask the network), so run them side by side.
        with ThreadPoolExecutor(max_workers=8) as pool:
            pool.map(self.load_version, self.rows)

    def load_version(self, row):
        pkg, status = row[0], row[1]
        if self.done[pkg[0]]:
            version = installed_version(pkg)
            # Python tools' "version" is the Python it runs on, not pipx's, so it can't be compared.
            newer = (available_version(pkg)
                     if pkg[5] and "apt-get install" in pkg[5] and pkg[0] != "Python tools" else None)
            if version and newer and newer not in ("latest", version) and \
                    not version.startswith(newer) and not newer.startswith(version):
                self.updates.add(pkg[0])
                GLib.idle_add(self.apply_filter)
                GLib.idle_add(self.set_status, status, f"✓ {version}\n⬆ {newer}",
                              f"Installed {version}; {newer} is available (Reinstall or run apt upgrade)")
            elif version:
                GLib.idle_add(self.set_status, status, f"✓ {version}", f"Installed version {version}")
        else:
            version = available_version(pkg)
            if version == "latest":
                GLib.idle_add(self.set_status, status, "Gets latest",
                              "The maker's installer always fetches their newest release")
            elif version:
                GLib.idle_add(self.set_status, status, f"Gets {version}",
                              f"Install will get version {version}")

    def show_pills(self, info):
        self.sysinfo = info
        for key, value in info:
            pill = Gtk.Box(spacing=6)
            pill.add_css_class("pill")
            k = Gtk.Label(label=key.upper())
            k.add_css_class("pill-key")
            pill.append(k)
            pill.append(Gtk.Label(label=value, ellipsize=3, max_width_chars=40, tooltip_text=value))
            child = Gtk.FlowBoxChild(child=pill, halign=Gtk.Align.START)
            self.pills.append(child)
        return False

    @staticmethod
    def set_status(status, text, tooltip):
        status.set_text(text)
        status.set_tooltip_text(tooltip)
        return False

    def selected(self):
        return [row[0] for row in self.rows if row[4].get_active()]

    def update_selection(self):
        count = len(self.selected())
        self.install_selected.set_label(f"Install selected ({count})" if count else "Install selected")
        self.install_selected.set_sensitive(count > 0 and not self.busy)

    def on_clear_selection(self, _button):
        for row in self.rows:
            row[4].set_active(False)

    def on_filter_button(self, button, group, option):
        # A tick on the chosen button, on top of the highlight, so the pick is obvious.
        button.set_label(("✓ " if button.get_active() else "") + option)
        if not button.get_active():
            return
        setattr(self, f"{group}_filter", "All" if option == "All sections" else option)
        self.apply_filter()

    def on_filter(self, _entry):
        self.apply_filter()

    def apply_filter(self):
        text = self.search.get_text().strip().lower()
        for (section, _), (header, rows) in zip(SECTIONS, self.headers):
            any_shown = False
            for pkg, _, _, widgets, _, _ in rows:
                done = self.done.get(pkg[0], False)
                shown = (text in " ".join(pkg[:3]).lower()
                         and self.section_filter in ("All", section)
                         and {"All": True, "Installed": done, "Not installed": not done,
                              "Updates": pkg[0] in self.updates}[self.state_filter])
                any_shown |= shown
                for widget in widgets:
                    widget.set_visible(shown)
            for widget in header:
                widget.set_visible(any_shown)
        return False

    def on_log_toggle(self, button):
        """Collapse the log down to its title bar, or bring it back at its old size."""
        show = button.get_active()
        button.set_label(("▾" if show else "▸") + " Log")
        if not show:
            self.log_position = self.paned.get_position()
        self.log_scroller.set_visible(show)
        # An oversized position is clamped, so the list takes all the room the log gave up.
        self.paned.set_position(self.log_position if show else 10000)

    def append(self, text):
        if not self.log_toggle.get_active() and text.startswith("\n==="):
            self.log_toggle.set_active(True)  # a new job starts: show its output
        buf = self.log.get_buffer()
        buf.insert(buf.get_end_iter(), text)
        self.log.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0)
        return False

    def on_open(self, _button, pkg):
        argv = launch_command(pkg)
        if not argv:
            self.append(f"\nCan't open {pkg[0]}: it isn't installed or has no launcher. Try Recheck.\n")
            return
        env = dict(os.environ, PATH=tool_path())
        try:
            # Detached, so closing this panel doesn't close what it opened.
            subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            self.append(f"\nOpened {pkg[0]}\n")
        except OSError as err:
            self.append(f"\nCouldn't open {pkg[0]}: {err}\n")

    def on_copy(self, _button, name, url):
        self.get_clipboard().set(url)
        self.append(f"Copied {name} link: {url}\n")

    def on_copy_log(self, _button):
        buf = self.log.get_buffer()
        self.get_clipboard().set(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False))

    def on_clear_log(self, _button):
        self.log.get_buffer().set_text("")

    def on_install(self, _button, pkg):
        name, url, cmd = pkg[0], pkg[4], pkg[5]
        if cmd is None:
            self.append(f"\n{name} has no scripted Linux install; opening {url}\n")
            Gtk.UriLauncher.new(url).launch(self, None, None)
            return
        self.start([(f"Installing {name}", cmd)])

    def on_install_selected(self, _button):
        pkgs = self.selected()
        # Plain apt installs are merged into one command, so there's one password prompt for all of them.
        apt_pkgs, jobs = [], []
        for pkg in pkgs:
            if match := APT_ONLY.match(pkg[5]):
                apt_pkgs.append((pkg[0], match.group(1)))
            else:
                jobs.append((f"Installing {pkg[0]}", pkg[5]))
        if apt_pkgs:
            names = ", ".join(name for name, _ in apt_pkgs)
            jobs.insert(0, (f"Installing {names}", apt(*(p for _, p in apt_pkgs))))
        self.on_clear_selection(None)
        self.append(f"\n### Installing {len(pkgs)} selected: {', '.join(p[0] for p in pkgs)} ###\n")
        self.start(jobs)

    def on_uninstall(self, _button, name, cmd):
        dialog = Gtk.AlertDialog(message=f"Uninstall {name}?", detail=f"This runs:\n{cmd}",
                                 buttons=["Cancel", "Uninstall"], cancel_button=0, default_button=0)

        def answered(d, result):
            try:
                if d.choose_finish(result) == 1:
                    self.start([(f"Uninstalling {name}", cmd)])
            except GLib.Error:
                pass  # dialog dismissed

        dialog.choose(self, None, answered)

    def start(self, jobs):
        """Run (title, command) jobs one after another in the background."""
        self.queue = list(jobs)
        self.busy = True
        self.refresh()
        self.run_next()

    def run_next(self):
        title, cmd = self.queue.pop(0)
        self.append(f"\n=== {title} ===\n$ {cmd}\n")
        threading.Thread(target=self.run, args=(title, cmd), daemon=True).start()
        return False

    def run(self, name, cmd):
        # Per-user tool folders may not be on PATH yet if they didn't exist at login,
        # so add them here so one install can use another (e.g. Latest Python needs uv).
        path = ":".join(EXTRA_PATHS) + ":" + os.environ.get("PATH", "")
        env = dict(os.environ, DEBIAN_FRONTEND="noninteractive", PATH=path)
        # No stdin, so an installer that asks a question fails instead of hanging the panel.
        proc = subprocess.Popen(["bash", "-c", cmd], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env=env)
        path_warning = False
        for line in proc.stdout:
            path_warning |= "not on your PATH" in line or "to your PATH" in line
            GLib.idle_add(self.append, line)
        code = proc.wait()
        if path_warning:
            GLib.idle_add(self.append, "ℹ The PATH note above is normal on a first install: open a new terminal "
                                       "(or log out and back in) and the command will be found.\n")
        result = "done ✓" if code == 0 else f"FAILED (exit {code})"
        GLib.idle_add(self.finish, f"=== {name}: {result} ===\n")

    def finish(self, msg):
        self.append(msg)
        if self.queue:
            self.refresh()
            return self.run_next()
        self.busy = False
        self.refresh()
        return False


def main():
    app = Gtk.Application(application_id="local.tuxsoftwaresuite")
    app.connect("activate", lambda a: TuxSoftwareSuite(a).present())
    app.run(None)


if __name__ == "__main__":
    main()
