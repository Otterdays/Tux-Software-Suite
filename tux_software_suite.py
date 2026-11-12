#!/usr/bin/env python3
"""Tux Software Suite (TSS): a small Ninite-style panel for installing Linux software one at a time."""
import json
import os
import re
import shutil
import socket
import signal
import platform
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

# The one place the version lives; build-deb.sh reads it from here.
VERSION = "1.21.0"

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
    f"{HOME}/.ghcup/bin",
    f"{HOME}/.juliaup/bin",
    f"{HOME}/miniforge3/bin",
    "/snap/bin",
    "/usr/games",  # Ubuntu keeps game binaries (Steam, SuperTuxKart, freeciv…) here
    "/var/lib/flatpak/exports/bin",
    f"{HOME}/.local/share/flatpak/exports/bin",
]

FLATHUB_REPO = "https://dl.flathub.org/repo/flathub.flatpakrepo"

# Prepended to installs that need another tool first, so they fail with a clear message.
NEEDS_NPM = "command -v npm >/dev/null || { echo 'Install Node.js first.'; exit 1; }; "
NEEDS_CODE = "command -v code >/dev/null || { echo 'Install VS Code first.'; exit 1; }; "
NEEDS_UV = "test -x ~/.local/bin/uv || { echo 'Install uv first.'; exit 1; }; "
NEEDS_FLATPAK = "command -v flatpak >/dev/null || { echo 'Install Flatpak + Flathub first.'; exit 1; }; "

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
    "Ollama": "Try 'ollama run llama3.2'. Models live in /usr/share/ollama and can be many GB.",
    "ChatGPT": "Linux preview supports Ubuntu 24.04/26.04 and Debian 13. It adds OpenAI's apt repo, "
               "so updates arrive with the rest of your system.",
    "Alpaca": "Install Ollama first for the smoothest setup, then pick 'Ollama (External)' in the app.",
    "Jan": "Pick a model in the Hub. Expect an 8 GB RAM minimum; 16 GB makes larger models comfortable.",
    "Speech Note": "Speech models download separately (often hundreds of MB). Turn on GPU acceleration "
                   "in the app's settings if you have a supported graphics card.",
    "PostgreSQL": "First login: 'sudo -u postgres psql'. Make yourself a user with 'sudo -u postgres createuser -s $USER'.",
    "Dev utilities": "Add 'eval \"$(direnv hook bash)\"' to ~/.bashrc to turn direnv on.",
    "Distrobox": "'distrobox create -i archlinux -n arch && distrobox enter arch'.",
    "Media tools": "'yt-dlp -x --audio-format mp3 URL' saves just the audio. "
                   "'gallery-dl URL' pulls down image galleries.",
    "Ardour": "The first start scans its plugins, so give it a minute before recording.",
    "MuseScore 4": "Ubuntu's own package is the old 2.x, so this installs the current 4.x from Flathub.",
    "Kooha": "It records through the Wayland portal, so it works on GNOME and KDE as they are.",
    "Flameshot": "On Wayland, screenshots go through the portal; 'flameshot gui' opens the full editor.",
    "darktable": "Leave your monitor on its sRGB profile and let darktable do the rest.",
    "LosslessCut": "It cuts at the nearest keyframe, so a cut can start a few frames early.",
    "Calibre": "'ebook-convert book.epub book.pdf' converts from the terminal too.",
    "Virtual Machine Manager": "Check virtualization is on in the BIOS if VMs are slow or won't start.",
    "Python build headers": "Fixes most 'error: command gcc failed' or 'Python.h: No such file' pip errors.",
    "Miniforge": "Keep conda for data-science stacks; use uv or venv for everything else.",
    "Haskell (GHCup)": "Open a new terminal, then 'ghcup tui' picks versions.",
    "mise": "Add 'eval \"$(~/.local/bin/mise activate bash)\"' to ~/.bashrc, then 'mise use node@lts'.",
    "Lutris": "Good for Battle.net, EA app and Ubisoft Connect games.",
    "Waydroid": "Needs a Wayland session (Ubuntu's default). Open Waydroid from the app menu and let it finish setup.",
    "MySQL": "Log in first with 'sudo mysql', then make a user: 'CREATE USER 'me'@'localhost' IDENTIFIED BY 'pass';'.",
    "VirtualBox": "For USB support add yourself to the vboxusers group: "
                   "'sudo usermod -aG vboxusers $USER', then log out and back in.",
    "atuin": "Run 'atuin register' for a free sync account, then add "
             "'eval \"$(atuin init bash)\"' to ~/.bashrc for Ctrl+R search.",
    "Bottles": "Make a 'Gaming' bottle for games; runners and DXVK updates live in Settings → Runners.",
    "Syncthing": "Once it's running, pair your devices in the web UI at http://127.0.0.1:8384.",
    "Goose": "Run 'goose' and pick a provider (it needs an API key). 'goose configure' changes that later.",
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
    return NEEDS_FLATPAK + f"flatpak install -y --noninteractive flathub {app_id}"


def deb(name, url):
    """Download a vendor's official .deb and install it with apt, so its dependencies come along."""
    return (f"tmp=$(mktemp -d) && curl -fL -o \"$tmp/{name}.deb\" '{url}' && "
            f"pkexec apt-get install -y \"$tmp/{name}.deb\"")


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


def github_deb(repo, asset, name):
    """Latest stable GitHub release .deb whose filename contains `asset`."""
    return (
        f"u=$(curl -fsSL 'https://api.github.com/repos/{repo}/releases?per_page=30' | python3 -c \""
        "import json,sys; print(next(a['browser_download_url'] for r in json.load(sys.stdin) "
        f"if not r['prerelease'] for a in r['assets'] if '{asset}' in a['name'] and a['name'].endswith('.deb')))\") && "
        f"d=$(mktemp -d) && curl -fL -o \"$d/{name}.deb\" \"$u\" && pkexec apt-get install -y \"$d/{name}.deb\""
    )


def chatbox():
    """Chatbox .deb from the official download host; the version comes from the latest GitHub release."""
    return (
        "v=$(curl -fsSL https://api.github.com/repos/chatboxai/chatbox/releases/latest | "
        "python3 -c \"import json,sys; print(json.load(sys.stdin)['tag_name'].lstrip('v'))\") && "
        "d=$(mktemp -d) && curl -fL -o \"$d/chatbox.deb\" "
        "\"https://download.chatboxai.app/releases/Chatbox-$v-amd64.deb\" && "
        "pkexec apt-get install -y \"$d/chatbox.deb\""
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
        ("Podman", "CLI", "Daemonless, rootless containers; a drop-in alternative to Docker", "podman",
         "https://podman.io/", apt("podman")),
        ("Dev utilities", "CLI", "shellcheck, direnv, httpie, just, hyperfine, git-delta", "shellcheck",
         "https://www.shellcheck.net/",
         apt("shellcheck", "direnv", "httpie", "just", "hyperfine", "git-delta")),
        (".NET 10 SDK", "Language", "Microsoft's C#/F# SDK (LTS), from Ubuntu's own archive", "dotnet",
         "https://dotnet.microsoft.com/", apt("dotnet-sdk-10.0")),
        ("PHP + Composer", "Language", "PHP command line and the Composer package manager", "php",
         "https://www.php.net/", apt("php-cli", "composer")),
        ("Ruby", "Language", "Ruby with headers, so native gems build", "ruby",
         "https://www.ruby-lang.org/", apt("ruby-full")),
    ]),
    ("Python & data", [
        ("Python build headers", "CLI", "python3-dev, tkinter, and the SSL/SQLite/zlib/ffi headers pip needs to build packages",
         "test -f /usr/include/python3*/Python.h", "https://docs.python.org/3/extending/",
         apt("python3-dev", "python3-tk", "libssl-dev", "libsqlite3-dev", "zlib1g-dev", "libffi-dev", "libbz2-dev")),
        ("pyenv", "CLI", "Build and switch between many Python versions per project", "pyenv",
         "https://github.com/pyenv/pyenv", apt("pyenv")),
        ("Poetry", "CLI", "Python dependency and packaging manager", "poetry",
         "https://python-poetry.org/", apt("python3-poetry")),
        ("JupyterLab", "CLI", "Notebooks in the browser, installed as a uv tool (install uv first)", "jupyter-lab",
         "https://jupyter.org/", NEEDS_UV + "~/.local/bin/uv tool install jupyterlab"),
        ("Ruff", "CLI", "Very fast Python linter and formatter, installed as a uv tool (install uv first)", "ruff",
         "https://docs.astral.sh/ruff/", NEEDS_UV + "~/.local/bin/uv tool install ruff"),
        ("Miniforge", "CLI", "conda + mamba from conda-forge for data science stacks, into ~/miniforge3", "test -d ~/miniforge3",
         "https://github.com/conda-forge/miniforge",
         "tmp=$(mktemp -d) && curl -fL -o \"$tmp/mf.sh\" "
         "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh && "
         "bash \"$tmp/mf.sh\" -b -p ~/miniforge3 && echo 'Run ~/miniforge3/bin/conda init bash to turn it on.'"),
        ("R", "Language", "R language for statistics and plotting", "R",
         "https://www.r-project.org/", apt("r-base")),
    ]),
    ("More languages", [
        ("Elixir + Erlang", "Language", "Elixir and the Erlang/OTP runtime it runs on", "elixir",
         "https://elixir-lang.org/", apt("elixir", "erlang")),
        ("Haskell (GHCup)", "Language", "GHC, cabal, stack and the language server, official GHCup installer", "ghcup",
         "https://www.haskell.org/ghcup/",
         "curl --proto '=https' --tlsv1.2 -sSf https://get-ghcup.haskell.org | "
         "BOOTSTRAP_HASKELL_NONINTERACTIVE=1 BOOTSTRAP_HASKELL_ADJUST_BASHRC=1 sh"),
        ("Julia", "Language", "Julia for numerical computing, official juliaup installer", "juliaup|julia",
         "https://julialang.org/install/", "curl -fsSL https://install.julialang.org | sh -s -- --yes"),
        ("Lua + LuaRocks", "Language", "Lua 5.4 and its package manager", "lua5.4|lua",
         "https://www.lua.org/", apt("lua5.4", "luarocks")),
        ("OCaml + opam", "Language", "OCaml compiler and the opam package manager", "ocaml",
         "https://ocaml.org/", apt("ocaml", "opam")),
        ("Nim", "Language", "Compiled language with Python-like syntax", "nim",
         "https://nim-lang.org/", apt("nim")),
        ("Clojure", "Language", "Lisp on the JVM, with Leiningen", "clojure",
         "https://clojure.org/", apt("clojure", "leiningen")),
        ("Zig", "Language", "Fast compiled language with its own build system and package manager", "zig",
         "https://ziglang.org/", apt("zig")),
        ("Crystal", "Language", "Ruby-like syntax on a fast compiled runtime", "crystal",
         "https://crystal-lang.org/", apt("crystal")),
        ("Racket", "Language", "Lisp family language built around the idea of making languages", "racket",
         "https://racket-lang.org/", apt("racket")),
        ("Ada (GNAT)", "Language", "GNAT Ada compiler, part of GCC; used for safety-critical systems", "gnatmake",
         "https://www.adacore.com/", apt("gnat")),
        ("Odin", "Language", "Systems language made for game development and data-oriented work", "odin",
         "https://odin-lang.org/", apt("odin")),
    ]),
    ("Build, debug & DevOps", [
        ("Build tools pack", "CLI", "meson, ccache, mold (fast linker), autoconf/automake/libtool, nasm", "meson",
         "https://mesonbuild.com/", apt("meson", "ccache", "mold", "autoconf", "automake", "libtool", "nasm")),
        ("Debug & profile pack", "CLI", "lldb, strace, ltrace, heaptrack, valgrind", "strace",
         "https://lldb.llvm.org/", apt("lldb", "strace", "ltrace", "heaptrack", "valgrind")),
        ("Git extras", "CLI", "pre-commit hooks, tig (git browser), git-crypt", "pre-commit",
         "https://pre-commit.com/", apt("pre-commit", "tig", "git-crypt")),
        ("mise", "CLI", "One tool for language versions, env vars and tasks per project, official installer", "mise",
         "https://mise.jdx.dev/", "curl -fsSL https://mise.run | sh"),
        ("AWS CLI", "CLI", "Amazon Web Services command line (run 'aws configure' after)", "aws",
         "https://aws.amazon.com/cli/", apt("awscli")),
        ("Ansible", "CLI", "Automate setup of servers and machines over SSH", "ansible",
         "https://www.ansible.com/", apt("ansible")),
        ("Podman Desktop", "App", "GUI for containers and Kubernetes, verified Flatpak (needs Flathub)",
         "io.podman_desktop.PodmanDesktop", "https://podman-desktop.io/", flatpak("io.podman_desktop.PodmanDesktop")),
        ("Dev Toolbox", "App", "JSON/base64/JWT/regex/hash helpers in one app, verified Flatpak (needs Flathub)",
         "me.iepure.devtoolbox", "https://flathub.org/apps/me.iepure.devtoolbox", flatpak("me.iepure.devtoolbox")),
        ("kubectl", "CLI", "Kubernetes command-line client, official Snap", "kubectl",
         "https://kubernetes.io/docs/reference/kubectl/", "pkexec snap install kubectl --classic"),
        ("Helm", "CLI", "Package manager for Kubernetes (charts)", "helm",
         "https://helm.sh/", "pkexec snap install helm --classic"),
        ("Minikube", "Tool", "A local one-node Kubernetes cluster in a VM or container", "minikube",
         "https://minikube.sigs.k8s.io/docs/start/",
         deb("minikube", "https://github.com/kubernetes/minikube/releases/latest/download/minikube_latest_amd64.deb")),
        ("Network tools", "Tool", "nmap (scan open ports) + Wireshark (inspect packets)", "nmap",
         "https://www.wireshark.org/", apt("nmap", "wireshark")),
    ]),
    ("Databases & APIs", [
        ("SQLite", "CLI", "sqlite3 shell for the single-file database", "sqlite3",
         "https://sqlite.org/", apt("sqlite3")),
        ("PostgreSQL", "CLI", "Postgres server + psql client; starts on boot", "psql",
         "https://www.postgresql.org/", apt("postgresql", "postgresql-client")),
        ("Redis", "CLI", "In-memory key-value store + redis-cli; starts on boot", "redis-server",
         "https://redis.io/", apt("redis-server")),
        ("Bruno", "App", "Offline, git-friendly API client (Postman alternative), verified Flatpak",
         "com.usebruno.Bruno", "https://www.usebruno.com/", flatpak("com.usebruno.Bruno")),
        ("MySQL", "CLI", "MySQL database server; starts on boot", "mysql",
         "https://www.mysql.com/", apt("mysql-server")),
        ("DBeaver Community", "Tool", "GUI client for PostgreSQL, MySQL, SQLite and many more, verified Flatpak",
         "io.dbeaver.DBeaverCommunity", "https://dbeaver.io/download/", flatpak("io.dbeaver.DBeaverCommunity")),
        ("Beekeeper Studio", "App", "Clean, simple GUI SQL client, from their apt repo so it updates",
         "dpkg -s beekeeper-studio", "https://www.beekeeperstudio.io/",
         "pkexec bash -c 'curl -fsSLo /usr/share/keyrings/beekeeper-archive-keyring.asc "
         "https://deb.beekeeperstudio.io/beekeeper.key && "
         "echo \"deb [signed-by=/usr/share/keyrings/beekeeper-archive-keyring.asc] "
         "https://deb.beekeeperstudio.io stable main\" > /etc/apt/sources.list.d/beekeeper-studio.list && "
         "apt-get update && apt-get install -y beekeeper-studio'"),
        ("Postman", "App", "Design, test and document REST APIs, official Snap", "postman",
         "https://www.postman.com/downloads/", "pkexec snap install postman"),
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
        ("Micro", "CLI", "Simple terminal editor with normal shortcuts (Ctrl+S, Ctrl+C, mouse)", "micro",
         "https://micro-editor.github.io/", apt("micro")),
        ("JetBrains Toolbox", "IDE", "Installs and updates PyCharm, WebStorm, CLion, GoLand, Rider…; tarball, so this opens the download page",
         "jetbrains-toolbox", "https://www.jetbrains.com/toolbox-app/", None),
        ("Cursor", "IDE", "Cursor's AI code editor; .deb/AppImage from their site, so this opens the download page",
         "cursor", "https://cursor.com/download", None),
        ("Antigravity IDE", "IDE", "Google's agentic IDE; tarball only, so this opens the download page",
         "antigravity", "https://antigravity.google/download?os=linux", None),
        ("Trae", "IDE", "ByteDance's AI IDE; .deb from their site, so this opens the download page",
         "trae", "https://www.trae.ai/download", None),
        ("Qoder IDE", "IDE", "Alibaba's AI IDE (Linux beta); .deb from their site, so this opens the download page",
         "qoder", "https://qoder.com/download", None),
        ("Emacs", "CLI", "The classic extensible editor, with a huge package ecosystem", "emacs",
         "https://www.gnu.org/software/emacs/", apt("emacs")),
        ("VSCodium", "IDE", "VS Code without Microsoft's branding or telemetry, verified Flatpak",
         "com.vscodium.codium", "https://vscodium.com/", flatpak("com.vscodium.codium")),
    ]),
    ("Android", [
        ("Android Studio", "IDE", "Google's Android IDE with SDK and emulator; Snap, auto-updates", "android-studio",
         "https://developer.android.com/studio", "pkexec snap install android-studio --classic"),
        ("Android SDK tools", "CLI", "Google's sdkmanager/avdmanager for building Android apps without Studio; needs a Java JDK",
         "sdkmanager", "https://developer.android.com/tools/releases/cmdline-tools",
         "command -v unzip >/dev/null || { echo 'Install Essentials first (needs unzip).'; exit 1; }; "
         "n=$(curl -fsSL https://dl.google.com/android/repository/repository2-1.xml | "
         "grep -oE 'commandlinetools-linux-[0-9]+_latest' | grep -oE '[0-9]+' | sort -n | tail -n1) && "
         "tmp=$(mktemp -d) && curl -fL -o \"$tmp/clt.zip\" "
         "\"https://dl.google.com/android/repository/commandlinetools-linux-${n}_latest.zip\" && "
         "rm -rf ~/.local/share/android-sdk && mkdir -p ~/.local/share/android-sdk/cmdline-tools ~/.local/bin && "
         "unzip -q \"$tmp/clt.zip\" -d \"$tmp\" && "
         "mv \"$tmp/cmdline-tools\" ~/.local/share/android-sdk/cmdline-tools/latest && "
         "ln -sf ~/.local/share/android-sdk/cmdline-tools/latest/bin/sdkmanager "
         "~/.local/share/android-sdk/cmdline-tools/latest/bin/avdmanager ~/.local/bin/ && "
         "echo 'Done. Run sdkmanager --licenses (needs a Java JDK from the Developers section).'"),
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
        ("Waydroid", "Tool", "Full Android in a container: run real Android apps on your desktop; needs a Wayland session",
         "waydroid", "https://waydro.id/",
         "pkexec bash -c 'apt-get install -y curl ca-certificates && curl -s https://repo.waydro.id | bash && "
         "apt-get update && apt-get install -y waydroid'"),
        ("Android File Transfer", "App", "Browse and copy files with a phone plugged in over USB (MTP), a calmer alternative to GNOME Files mounts",
         "android-file-transfer", "https://github.com/whoozle/android-file-transfer-linux",
         apt("android-file-transfer")),
        ("Universal Android Debloater", "App", "UAD-ng: safely disable the bloat apps a non-rooted phone shipped with",
         "uad-ng", "https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation",
         "mkdir -p ~/.local/bin && curl -fL -o ~/.local/bin/uad-ng "
         "https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation/releases/latest/download/uad-ng-linux "
         "&& chmod +x ~/.local/bin/uad-ng"),
        ("Heimdall", "Tool", "Flash firmware onto Samsung Galaxy devices over USB, the open-source Odin",
         "heimdall", "https://github.com/benjamin-dobell/heimdall", apt("heimdall-flash")),
        ("apktool", "Tool", "Decode and rebuild an APK's resources and smali (Android reverse engineering)",
         "apktool", "https://apktool.org/", apt("apktool")),
        ("jadx", "Tool", "Decompiles APKs back into readable Java, with a GUI (jadx-gui); needs a Java JDK",
         "jadx", "https://github.com/skylot/jadx",
         "command -v unzip >/dev/null || { echo 'Install Essentials first (needs unzip).'; exit 1; }; "
         "command -v java >/dev/null || { echo 'Install Java first (Developers section).'; exit 1; }; "
         "tmp=$(mktemp -d) && u=$(curl -fsSL 'https://api.github.com/repos/skylot/jadx/releases/latest' | python3 -c \""
         "import json,sys; print(next(a['browser_download_url'] for a in json.load(sys.stdin)['assets'] "
         "if a['name'].endswith('.zip') and 'gui' not in a['name']))\") && curl -fL -o \"$tmp/jadx.zip\" \"$u\" && "
         "rm -rf ~/.local/share/jadx && mkdir -p ~/.local/share/jadx && unzip -q \"$tmp/jadx.zip\" -d ~/.local/share/jadx && "
         "mkdir -p ~/.local/bin && "
         "ln -sf ~/.local/share/jadx/bin/jadx ~/.local/share/jadx/bin/jadx-gui ~/.local/bin/"),
        ("Flutter", "Language", "Google's cross-platform app SDK (Android, Linux, web), official Snap", "flutter",
         "https://docs.flutter.dev/get-started/install/linux",
         "pkexec snap install flutter --classic && echo 'Downloading the Flutter SDK (about 1.5 GB)...' && "
         "/snap/bin/flutter --version"),
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
        ("Gemini CLI", "CLI", "Google's Gemini coding agent, from npm (install Node.js first)", "gemini",
         "https://github.com/google-gemini/gemini-cli", NEEDS_NPM + "pkexec npm install -g @google/gemini-cli"),
        ("GitHub Copilot CLI", "CLI", "GitHub's Copilot agent in the terminal, from npm (install Node.js first)",
         "copilot", "https://github.com/github/copilot-cli", NEEDS_NPM + "pkexec npm install -g @github/copilot"),
        ("Amp", "CLI", "Sourcegraph's coding agent, from npm (install Node.js first)", "amp",
         "https://ampcode.com/", NEEDS_NPM + "pkexec npm install -g @sourcegraph/amp"),
        ("Cursor CLI", "CLI", "Cursor's agent in the terminal (cursor-agent), official installer", "cursor-agent",
         "https://cursor.com/cli", "curl -fsS https://cursor.com/install | bash"),
        ("Aider", "CLI", "Open-source pair-programming agent for any model, official installer (uses uv)", "aider",
         "https://aider.chat/", "curl -LsSf https://aider.chat/install.sh | sh"),
        ("Z Code", "CLI", "Z.ai's open-source agent; no published Linux build yet, so this opens GitHub",
         "zcode", "https://github.com/zai-org/ZCode", None),
        ("Goose", "CLI", "Block's open-source coding agent, official installer (lands in ~/.local/bin)", "goose",
         "https://block.github.io/goose/",
         "curl -fsSL https://github.com/block/goose/releases/download/stable/download_cli.sh | CONFIGURE=false bash"),
        ("Qwen Code", "CLI", "Qwen's coding agent (qwen), from npm (install Node.js first)", "qwen",
         "https://github.com/QwenLM/qwen-code", NEEDS_NPM + "pkexec npm install -g @qwen-code/qwen-code"),
    ]),
    ("AI apps", [
        ("ChatGPT", "App", "OpenAI's ChatGPT, Work and Codex in one app (Linux preview for Ubuntu 24.04+/Debian 13)",
         "chatgpt", "https://learn.chatgpt.com/docs/linux/linux-app",
         deb("chatgpt", "https://persistent.oaistatic.com/codex-app-prod/linux/deb/latest/chatgpt_amd64.deb")),
        ("Claude Desktop", "App", "Anthropic's desktop app (Linux beta), from their apt repo so it updates",
         "claude-desktop", "https://code.claude.com/docs/en/desktop-linux", CLAUDE_DESKTOP),
        ("T3 Code (release)", "App", "T3 Code stable build (amd64 .deb from GitHub releases); shares a package with Nightly",
         "dpkg -s t3code", "https://github.com/pingdotgg/t3code/releases", t3code(False)),
        ("T3 Code (nightly)", "App", "T3 Code newest nightly pre-release (amd64 .deb); replaces the release build",
         "dpkg -s t3code", "https://github.com/pingdotgg/t3code/releases", t3code(True)),
        ("Ollama", "Runtime", "Run open models locally (llama, qwen, gemma…); official installer, adds a service",
         "ollama", "https://ollama.com/download/linux", "pkexec sh -c 'curl -fsSL https://ollama.com/install.sh | sh'"),
        ("Alpaca", "App", "Native GTK chat client for local models via Ollama, verified Flatpak (needs Flathub)",
         "com.jeffser.Alpaca", "https://jeffser.com/alpaca/", flatpak("com.jeffser.Alpaca")),
        ("LM Studio", "App", "Desktop app for local models; AppImage only, so this opens the download page",
         "lm-studio|lmstudio", "https://lmstudio.ai/download", None),
        ("Jan", "App", "Open-source offline ChatGPT alternative, local models plus your own cloud API keys (needs Flathub)",
         "ai.jan.Jan", "https://jan.ai/download", flatpak("ai.jan.Jan")),
        ("Cherry Studio", "App", "Multi-provider AI workspace: chat, agents, knowledge base and image tools; official .deb",
         "CherryStudio|cherry-studio", "https://github.com/CherryHQ/cherry-studio/releases",
         github_deb("CherryHQ/cherry-studio", "linux-x64.deb", "cherry-studio")),
        ("Chatbox", "App", "Desktop client for OpenAI, Claude, Gemini, Ollama and more; official .deb",
         "xyz.chatboxapp.app", "https://chatboxai.app/", chatbox()),
        ("AnythingLLM", "App", "All-in-one private AI app for chat, documents and RAG; AppImage only, so this opens the download page",
         "anythingllm-desktop|anythingllm", "https://anythingllm.com/download", None),
        ("Speech Note", "App", "Offline speech-to-text, text-to-speech and translation with Whisper and friends (needs Flathub)",
         "net.mkiol.SpeechNote", "https://github.com/mkiol/dsnote", flatpak("net.mkiol.SpeechNote")),
        ("Antigravity", "App", "Google's Antigravity 2.0 agent app; tarball only, so this opens the download page",
         "antigravity-hub", "https://antigravity.google/download?os=linux", None),
    ]),
    ("Terminal & power tools", [
        ("Ghostty", "App", "Fast, GPU-accelerated terminal", "ghostty",
         "https://ghostty.org/", apt("ghostty")),
        ("Kitty", "App", "GPU terminal with tabs, splits and image support", "kitty",
         "https://sw.kovidgoyal.net/kitty/", apt("kitty")),
        ("Alacritty", "App", "Minimal, very fast GPU terminal", "alacritty",
         "https://alacritty.org/", apt("alacritty")),
        ("fish shell", "CLI", "Friendly shell with autosuggestions out of the box; run 'fish' to try it", "fish",
         "https://fishshell.com/", apt("fish")),
        ("System pack", "CLI", "htop, fastfetch (system summary), ncdu (what's eating my disk)", "fastfetch",
         "https://github.com/fastfetch-cli/fastfetch", apt("htop", "fastfetch", "ncdu")),
        ("Distrobox", "CLI", "Run any distro (Arch, Fedora…) inside your terminal; needs Podman or Docker",
         "distrobox", "https://distrobox.it/", apt("distrobox")),
        ("Modern CLI pack", "CLI", "ripgrep, fd, fzf, bat, eza, zoxide, btop, tldr, jq, tmux", "rg",
         "https://github.com/BurntSushi/ripgrep",
         apt("ripgrep", "fd-find", "fzf", "bat", "eza", "zoxide", "btop", "tealdeer", "jq", "tmux")),
        ("Shell setup", "Tool", "Adds aliases (bat, fd, ls→eza) and zoxide/fzf/starship hooks to ~/.bashrc",
         f"grep -qF '{SHELL_MARK}' ~/.bashrc", "https://github.com/ajeetdsouza/zoxide", SHELL_SETUP),
        ("Starship prompt", "CLI", "Clean, informative shell prompt (git branch, language versions)", "starship",
         "https://starship.rs/", apt("starship")),
        ("lazygit", "CLI", "Terminal UI for git: stage, commit and rebase with a few keys", "lazygit",
         "https://github.com/jesseduffield/lazygit", apt("lazygit")),
        ("atuin", "CLI", "Searchable, syncable shell history — the Ctrl+R replacement", "atuin",
         "https://atuin.sh/", apt("atuin")),
        ("CLI extras pack", "CLI", "gping, procs, bandwhich, sd (sed), xh (HTTP), glow, duf, just", "gping",
         "https://github.com/orf/gping",
         apt("gping", "procs", "bandwhich", "sd", "xh", "glow", "duf", "just")),
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
        ("ONLYOFFICE", "App", "Office suite that renders .docx/.xlsx like Word and Excel (needs Flathub)",
         "org.onlyoffice.desktopeditors", "https://www.onlyoffice.com/", flatpak("org.onlyoffice.desktopeditors")),
        ("Pandoc", "CLI", "Convert between Markdown, HTML, Word, LaTeX, PDF and more", "pandoc",
         "https://pandoc.org/", apt("pandoc")),
        ("GIMP", "App", "Photo and image editor", "gimp",
         "https://www.gimp.org/", apt("gimp")),
        ("GNOME Tweaks", "Tool", "Extra desktop settings: fonts, themes, startup apps", "gnome-tweaks",
         "https://gitlab.gnome.org/GNOME/gnome-tweaks", apt("gnome-tweaks")),
        ("Timeshift", "Tool", "System snapshots, so you can undo a broken update", "timeshift",
         "https://github.com/linuxmint/timeshift", apt("timeshift")),
        ("Google Chrome", "App", "Google's browser, official .deb (adds Google's apt repo so it updates)",
         "google-chrome", "https://www.google.com/chrome/",
         deb("chrome", "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb")),
        ("Brave", "App", "Privacy browser with built-in ad blocking, verified Flatpak (needs Flathub)",
         "com.brave.Browser", "https://brave.com/linux/", flatpak("com.brave.Browser")),
        ("Obsidian", "App", "Markdown notes and knowledge base, verified Flatpak (needs Flathub)",
         "md.obsidian.Obsidian", "https://obsidian.md/", flatpak("md.obsidian.Obsidian")),
        ("Zotero", "App", "Reference manager: collect, cite and format research papers (needs Flathub)",
         "org.zotero.Zotero", "https://www.zotero.org/", flatpak("org.zotero.Zotero")),
        ("Anki", "App", "Spaced-repetition flashcards for learning anything (needs Flathub)",
         "net.ankiweb.Anki", "https://apps.ankiweb.net/", flatpak("net.ankiweb.Anki")),
        ("Telegram", "App", "Cloud messenger, verified Flatpak (needs Flathub)", "org.telegram.desktop",
         "https://desktop.telegram.org/", flatpak("org.telegram.desktop")),
        ("Signal", "App", "Private messenger with end-to-end encryption, verified Flatpak (needs Flathub)",
         "org.signal.Signal", "https://signal.org/download/", flatpak("org.signal.Signal")),
        ("Element", "App", "Chat on the open Matrix network; self-hostable, verified Flatpak",
         "im.riot.Riot", "https://element.io/", flatpak("im.riot.Riot")),
        ("Thunderbird", "App", "Mozilla's email, calendar and chat client, official Snap", "thunderbird",
         "https://www.thunderbird.net/", "pkexec snap install thunderbird"),
        ("Zoom", "App", "Video meetings, official .deb from zoom.us", "zoom",
         "https://zoom.us/download", deb("zoom", "https://zoom.us/client/latest/zoom_amd64.deb")),
        ("Bitwarden", "App", "Open-source password manager, verified Flatpak (needs Flathub)",
         "com.bitwarden.desktop", "https://bitwarden.com/download/", flatpak("com.bitwarden.desktop")),
        ("KeePassXC", "App", "Offline password manager; your vault is one encrypted file", "keepassxc",
         "https://keepassxc.org/", apt("keepassxc")),
        ("qBittorrent", "App", "Clean, ad-free torrent client", "qbittorrent",
         "https://www.qbittorrent.org/", apt("qbittorrent")),
        ("Spotify", "App", "Music streaming (needs Flathub)", "com.spotify.Client",
         "https://www.spotify.com/download/linux/", flatpak("com.spotify.Client")),
        ("Flatseal", "Tool", "Review and change Flatpak app permissions (needs Flathub)",
         "com.github.tchx84.Flatseal", "https://flathub.org/apps/com.github.tchx84.Flatseal",
         flatpak("com.github.tchx84.Flatseal")),
        ("Gear Lever", "Tool", "Adds AppImages to the app menu and updates them (needs Flathub)",
         "it.mijorus.gearlever", "https://flathub.org/apps/it.mijorus.gearlever",
         flatpak("it.mijorus.gearlever")),
        ("GParted", "Tool", "Resize, format and fix disk partitions", "gparted",
         "https://gparted.org/", apt("gparted")),
        ("Virtual Machine Manager", "App", "Run Windows or other Linux VMs with KVM (log out and in after)",
         "virt-manager", "https://virt-manager.org/", apt("virt-manager")),
        ("VirtualBox", "App", "Run Windows or other OSes in virtual machines, from Oracle", "virtualbox",
         "https://www.virtualbox.org/", apt("virtualbox")),
        ("GNOME Boxes", "App", "Simple, quick virtual machines (KVM), GNOME's own", "gnome-boxes",
         "https://wiki.gnome.org/Apps/Boxes", apt("gnome-boxes")),
        ("BleachBit", "Tool", "Clean caches and junk files to free disk space", "bleachbit",
         "https://www.bleachbit.org/", apt("bleachbit")),
        ("Stacer", "App", "System monitor and cleaner with a dashboard", "stacer",
         "https://oguzhaninan.github.io/Stacer-WebSite/", apt("stacer")),
        ("Syncthing", "CLI", "Continuously sync folders between your own devices", "syncthing",
         "https://syncthing.net/", apt("syncthing")),
        ("Foliate", "App", "Modern e-book reader for EPUB and more", "foliate",
         "https://johnfactotum.github.io/foliate/", apt("foliate")),
        ("Zathura", "App", "Minimal, keyboard-driven document viewer (PDF, PostScript, DjVu)", "zathura",
         "https://pwmt.org/projects/zathura/", apt("zathura", "zathura-pdf-poppler", "zathura-ps", "zathura-djvu")),
    ]),
    ("Creative & media", [
        ("OBS Studio", "App", "Screen recording and streaming", "obs",
         "https://obsproject.com/", apt("obs-studio")),
        ("Kooha", "App", "Simple screen recorder that works on Wayland too (needs Flathub)",
         "io.github.seadve.Kooha", "https://github.com/SeaDve/Kooha", flatpak("io.github.seadve.Kooha")),
        ("Flameshot", "App", "Screenshots you can annotate, then copy to the clipboard", "flameshot",
         "https://flameshot.org/", apt("flameshot")),
        ("mpv", "App", "Lightweight, keyboard-driven video player", "mpv",
         "https://mpv.io/", apt("mpv")),
        ("Media tools", "CLI", "ffmpeg (convert anything) + yt-dlp (video) + gallery-dl (images)", "ffmpeg",
         "https://ffmpeg.org/", apt("ffmpeg", "yt-dlp", "gallery-dl")),
        ("MediaInfo", "CLI", "Show the codec, bitrate and metadata of any media file", "mediainfo",
         "https://mediaarea.net/en/MediaInfo", apt("mediainfo")),
        ("MKVToolNix", "CLI", "Remux, merge and tag Matroska files without re-encoding", "mkvmerge",
         "https://mkvtoolnix.org/", apt("mkvtoolnix")),
        ("HandBrake", "App", "Convert and shrink video files", "ghb|handbrake",
         "https://handbrake.fr/", apt("handbrake")),
        ("Kdenlive", "App", "Video editor with multi-track timeline", "kdenlive",
         "https://kdenlive.org/", apt("kdenlive")),
        ("Shotcut", "App", "Fast video editor that opens almost any format", "shotcut",
         "https://www.shotcut.org/", apt("shotcut")),
        ("OpenShot", "App", "Drag-and-drop video editor, easy to learn", "openshot-qt",
         "https://www.openshot.org/", apt("openshot-qt")),
        ("Flowblade", "App", "Timeline video editor that stays out of your way", "flowblade",
         "https://github.com/jliljebl/flowblade", apt("flowblade")),
        ("LosslessCut", "App", "Cut and trim video without re-encoding (needs Flathub)", "no.mifi.losslesscut",
         "https://losslesscut.app/", flatpak("no.mifi.losslesscut")),
        ("Audacity", "App", "Record and edit audio", "audacity",
         "https://www.audacityteam.org/", apt("audacity")),
        ("Ardour", "App", "Multitrack recording and mixing, the professional free DAW", "ardour|ardour9|ardour8",
         "https://ardour.org/", apt("ardour")),
        ("LMMS", "App", "Make beats with MIDI and samples", "lmms",
         "https://lmms.io/", apt("lmms")),
        ("Mixxx", "App", "DJ software: mix, loop and record live sets", "mixxx",
         "https://www.mixxx.org/", apt("mixxx")),
        ("Hydrogen", "App", "Pattern-based drum machine with plenty of sample kits", "hydrogen",
         "http://hydrogen-music.org/", apt("hydrogen")),
        ("Qtractor", "App", "Multitrack audio and MIDI sequencer", "qtractor",
         "https://qtractor.sourceforge.io/", apt("qtractor")),
        ("Sonic Pi", "App", "Live coding: make music by writing code", "sonic-pi",
         "https://sonic-pi.net/", apt("sonic-pi")),
        ("MuseScore 4", "App", "Write, edit and print sheet music (needs Flathub)", "org.musescore.MuseScore",
         "https://musescore.org/", flatpak("org.musescore.MuseScore")),
        ("MusicBrainz Picards", "App", "Tag your music automatically from the MusicBrainz database", "picard",
         "https://picard.musicbrainz.org/", apt("picard")),
        ("Inkscape", "App", "Vector graphics: logos, icons, SVG", "inkscape",
         "https://inkscape.org/", apt("inkscape")),
        ("Krita", "App", "Digital painting and illustration", "krita",
         "https://krita.org/", apt("krita")),
        ("Photoflare", "App", "Lightweight image editor for quick fixes", "photoflare",
         "https://photoflare.io/", apt("photoflare")),
        ("darktable", "App", "Non-destructive RAW developer for photographers", "darktable",
         "https://www.darktable.org/", apt("darktable")),
        ("RawTherapee", "App", "RAW developer with very fine control over the look", "rawtherapee",
         "https://www.rawtherapee.com/", apt("rawtherapee")),
        ("digiKam", "App", "Photo library manager: tag, rate, geotag and search", "digikam",
         "https://www.digikam.org/", apt("digikam")),
        ("Entangle", "App", "Control your camera tethered from the desktop", "entangle",
         "https://entangle-photo.org/", apt("entangle")),
        ("Synfig Studio", "App", "Vector 2D animation and tweening", "synfig",
         "https://www.synfig.org/", apt("synfig")),
        ("Pencil2D", "App", "Simple 2D animation and storyboards", "pencil2d",
         "https://www.pencil2d.org/", apt("pencil2d")),
        ("Pixelorama", "App", "Pixel art and sprite animation (needs Flathub)", "com.orama_interactive.Pixelorama",
         "https://pixelorama.org/", flatpak("com.orama_interactive.Pixelorama")),
        ("Natron", "App", "Node-based VFX and motion graphics compositor (needs Flathub)", "fr.natron.Natron",
         "https://natrongithub.github.io/", flatpak("fr.natron.Natron")),
        ("Blender", "App", "3D modelling, animation and rendering", "blender",
         "https://www.blender.org/", apt("blender")),
        ("OpenSCAD", "App", "Code 3D models with a small scripting language", "openscad",
         "https://openscad.org/", apt("openscad")),
        ("FreeCAD", "App", "Parametric CAD for machine parts and models (needs Flathub)", "org.freecad.FreeCAD",
         "https://www.freecad.org/", flatpak("org.freecad.FreeCAD")),
        ("FontForge", "App", "Draw and edit your own fonts", "fontforge",
         "https://fontforge.org/", apt("fontforge")),
        ("Scribus", "App", "Desktop publishing: posters, flyers and brochures", "scribus",
         "https://www.scribus.net/", apt("scribus")),
        ("Calibre", "App", "E-book library, editor and format converter", "calibre",
         "https://calibre-ebook.com/", apt("calibre")),
        ("Xournal++", "App", "Handwritten notes and PDF annotation", "xournalpp",
         "https://xournalpp.github.io/", apt("xournalpp")),
        ("Aegisub", "App", "Subtitle editor that times lines to the audio", "aegisub-3.2|aegisub",
         "https://aegisub.org/", apt("aegisub")),
        ("Gaupol", "App", "Lightweight subtitle editor and translator", "gaupol",
         "https://sourceforge.net/projects/gaupol/", apt("gaupol")),
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
         deb("discord", "https://discord.com/api/download?platform=linux&format=deb")),
        ("Prism Launcher", "App", "Minecraft launcher for many instances and modpacks, verified Flatpak",
         "org.prismlauncher.PrismLauncher", "https://prismlauncher.org/",
         flatpak("org.prismlauncher.PrismLauncher")),
        ("RetroArch", "App", "One front end for classic console emulators", "retroarch",
         "https://www.retroarch.com/", apt("retroarch")),
        ("PCSX2", "App", "PlayStation 2 emulator, verified Flatpak (needs Flathub)", "net.pcsx2.PCSX2",
         "https://pcsx2.net/", flatpak("net.pcsx2.PCSX2")),
        ("Wine + Winetricks", "Tool", "Run Windows programs outside Steam; Winetricks adds runtimes and fonts",
         "wine", "https://www.winehq.org/", apt("wine", "winetricks")),
        ("Bottles", "App", "Run Windows software and games in isolated prefixes (needs Flathub)",
         "com.usebottles.bottles", "https://usebottles.com/", flatpak("com.usebottles.bottles")),
        ("Godot", "Tool", "Open-source game engine for 2D and 3D games", "godot",
         "https://godotengine.org/", apt("godot")),
        ("DOSBox", "App", "Play classic MS-DOS games", "dosbox",
         "https://www.dosbox.com/", apt("dosbox")),
        ("ScummVM", "App", "Replay classic point-and-click adventure games", "scummvm",
         "https://www.scummvm.org/", apt("scummvm")),
        ("SuperTuxKart", "App", "Free and open-source kart racer", "supertuxkart",
         "https://supertuxkart.net/", apt("supertuxkart")),
        ("0 A.D.", "App", "Free historical real-time strategy game", "0ad",
         "https://www.play0ad.com/", apt("0ad")),
        ("Hedgewars", "App", "Worms-style turn-based strategy with hedgehogs", "hedgewars",
         "https://www.hedgewars.org/", apt("hedgewars")),
        ("Battle for Wesnoth", "App", "Turn-based fantasy strategy with a huge free campaign", "wesnoth",
         "https://www.wesnoth.org/", apt("wesnoth")),
        ("Freeciv", "App", "Free Civilization-style strategy game", "freeciv-gtk3.22",
         "https://www.freeciv.org/", apt("freeciv")),
        ("OpenTTD", "App", "Open-source transport simulation game", "openttd",
         "https://www.openttd.org/", apt("openttd")),
    ]),
]
PACKAGES = [pkg for _, pkgs in SECTIONS for pkg in pkgs]
PACKAGE_NAMES = {pkg[0] for pkg in PACKAGES}

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
    "Cursor CLI": None,
    "JupyterLab": "~/.local/bin/uv tool uninstall jupyterlab",
    "Ruff": "~/.local/bin/uv tool uninstall ruff",
    "Miniforge": None,  # would delete every conda environment
    "Haskell (GHCup)": "~/.ghcup/bin/ghcup nuke",
    "Julia": "~/.juliaup/bin/juliaup self uninstall",
    "mise": "rm -f ~/.local/bin/mise && echo 'Removed. Delete the mise lines from ~/.bashrc too.'",
    "Python build headers": None,  # other dev packages often depend on these
    "Aider": "~/.local/bin/uv tool uninstall aider-chat",
    "Ollama": None,  # root service, user and models; follow ollama.com's uninstall steps
    "PostgreSQL": None,  # would leave (or with purge, delete) your databases
    "MySQL": None,  # same as PostgreSQL: the data in /var/lib/mysql is the point
    "Zoom": "pkexec apt-get remove -y zoom",
    "Minikube": "pkexec apt-get remove -y minikube",
    "Beekeeper Studio": "pkexec bash -c 'apt-get remove -y beekeeper-studio && "
                        "rm -f /etc/apt/sources.list.d/beekeeper-studio.list "
                        "/usr/share/keyrings/beekeeper-archive-keyring.asc'",
    "Goose": "rm -f ~/.local/bin/goose",
    "Google Chrome": "pkexec apt-get remove -y google-chrome-stable",
    "Verdent": "code --uninstall-extension verdentai.verdent",
    "Claude Desktop": "pkexec apt-get remove -y claude-desktop",
    "ChatGPT": "pkexec apt-get remove -y chatgpt",
    "Cherry Studio": "pkexec apt-get remove -y cherrystudio",
    "Chatbox": "pkexec apt-get remove -y xyz.chatboxapp.app",
    "T3 Code (release)": "pkexec apt-get remove -y t3code",
    "T3 Code (nightly)": "pkexec apt-get remove -y t3code",
    "Shell setup": f"sed -i '/{SHELL_MARK}/,/# <<< dev-installer shell setup <<</d' ~/.bashrc && "
                   "echo 'Removed from ~/.bashrc.'",
    "Flatpak + Flathub": "pkexec apt-get remove -y flatpak",
    "Steam": "pkexec apt-get remove -y steam-installer steam-devices",
    "Discord": "pkexec apt-get remove -y discord",
    "Flutter": "pkexec snap remove flutter",
    "Android SDK tools": "rm -rf ~/.local/share/android-sdk ~/.local/bin/sdkmanager ~/.local/bin/avdmanager",
    "Waydroid": "pkexec bash -c 'apt-get remove -y waydroid && rm -f /etc/apt/sources.list.d/waydroid.list'",
    "Universal Android Debloater": "rm -f ~/.local/bin/uad-ng",
    "jadx": "rm -rf ~/.local/share/jadx ~/.local/bin/jadx ~/.local/bin/jadx-gui",
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
    cmd = cmd.removeprefix(NEEDS_NPM).removeprefix(NEEDS_CODE).removeprefix(NEEDS_FLATPAK)
    if match := APT_ONLY.match(cmd):
        return "pkexec apt-get remove -y " + match.group(1)
    if match := re.fullmatch(r"pkexec snap install (\S+)(?: --classic)?", cmd):
        return f"pkexec snap remove {match.group(1)}"
    if match := re.fullmatch(r"flatpak install -y --noninteractive flathub (\S+)", cmd):
        return f"flatpak uninstall -y --noninteractive {match.group(1)}"
    if match := re.fullmatch(r"pkexec npm install -g (.+)", cmd):
        return f"pkexec npm uninstall -g {match.group(1)}"
    return None


# Programs that need another program first (beyond the NEEDS_* prefixes in their install command).
DEPENDS = {"SDKMAN": ["Essentials"], "Gradle": ["SDKMAN"], "fnm": ["Essentials"],
           "Platform tools (adb)": ["Essentials"], "LazyVim starter": ["Neovim"],
           "Docker": [], "Distrobox": ["Podman"],
           "Android SDK tools": ["Essentials"], "Universal Android Debloater": ["Platform tools (adb)"]}
PREFIX_DEPENDS = ((NEEDS_NPM, "Node.js"), (NEEDS_CODE, "VS Code"), (NEEDS_UV, "uv"),
                  (NEEDS_FLATPAK, "Flatpak + Flathub"))

# One-click starter sets for the Quick picks menu.
PRESETS = [
    ("Fresh install basics", ["Essentials", "Python tools", "Flatpak + Flathub", "VLC", "Timeshift",
                              "Modern CLI pack", "Google Chrome"]),
    ("Web developer", ["Essentials", "Node.js", "TypeScript", "pnpm", "VS Code", "Docker", "GitHub CLI",
                       "Google Chrome"]),
    ("Python & data", ["Essentials", "Python build headers", "uv", "Latest Python (via uv)", "JupyterLab",
                       "Ruff", "VS Code", "GitHub CLI"]),
    ("AI coding agents", ["Essentials", "Node.js", "Claude Code", "Codex CLI", "Gemini CLI", "OpenCode",
                          "GitHub CLI"]),
    ("Systems & game dev", ["Essentials", "C/C++ toolchain", "Build tools pack", "Debug & profile pack",
                            "Rust", "Go", "VS Code"]),
    ("Gamer", ["Steam", "Lutris", "GameMode + MangoHud", "Discord", "Flatpak + Flathub", "ProtonUp-Qt"]),
    ("Video & photo creator", ["Flatpak + Flathub", "Shotcut", "darktable", "Audacity", "Inkscape",
                               "Krita", "Blender", "HandBrake"]),
    ("Music maker", ["Flatpak + Flathub", "Ardour", "LMMS", "Hydrogen", "MuseScore 4", "Sonic Pi",
                     "MusicBrainz Picards"]),
]


def prerequisites(pkg):
    """Names of the programs this one needs installed first."""
    needs = list(DEPENDS.get(pkg[0], []))
    needs += [name for prefix, name in PREFIX_DEPENDS if pkg[5] and pkg[5].startswith(prefix)]
    return needs


def online():
    """True if the internet answers; a quick check so an install can say 'no connection' instead of timing out."""
    for host in (("1.1.1.1", 443), ("8.8.8.8", 443)):
        try:
            socket.create_connection(host, timeout=3).close()
            return True
        except OSError:
            continue
    return False


def apt_cache_stale():
    """True if apt hasn't updated in the last day (a fresh install often has an empty cache)."""
    for stamp in ("/var/lib/apt/periodic/update-success-stamp", "/var/cache/apt/pkgcache.bin"):
        try:
            return time.time() - os.stat(stamp).st_mtime > 86400
        except OSError:
            continue
    return True


def with_apt_update(cmd):
    """Refresh apt first when its package lists are old, inside the same password prompt."""
    if cmd and cmd.startswith("pkexec apt-get install -y ") and apt_cache_stale():
        return "pkexec bash -c 'apt-get update && " + cmd.removeprefix("pkexec ") + "'"
    return cmd


def is_installed(check):
    if " " in check:
        return subprocess.run(["bash", "-c", check], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    path = os.environ.get("PATH", "") + ":" + ":".join(EXTRA_PATHS)
    return any(shutil.which(cmd, path=path) for cmd in check.split("|"))


# The few tools that don't take --version.
VERSION_ARGS = {"go": ["version"], "javac": ["-version"]}
# Rows whose install check isn't the program whose version matters.
VERSION_EXE = {"Node.js": "node"}


# Command-line tools worth opening in a terminal window; the rest (git, cargo…) do nothing on their own.
OPEN_IN_TERMINAL = {"Claude Code", "Codex CLI", "OpenCode", "Devin CLI", "Qoder CLI", "MiniMax Code",
                    "Antigravity CLI", "DeepSeek Harness", "Neovim", "lazygit", "Gemini CLI",
                    "GitHub Copilot CLI", "Amp", "Cursor CLI", "Aider", "Micro", "fish shell"}
# Programs whose install check isn't a command name, and the command that opens them.
LAUNCHERS = {"T3 Code (release)": "t3code", "T3 Code (nightly)": "t3code"}
# Terminal emulators and the flag that makes them run a command, in order of preference.
TERMINALS = [("ghostty", "-e"), ("gnome-terminal", "--"), ("ptyxis", "-x"), ("kgx", "-e"),
             ("konsole", "-e"), ("x-terminal-emulator", "-e")]


def tool_path():
    return os.environ.get("PATH", "") + ":" + ":".join(EXTRA_PATHS)


def launch_command(pkg):
    """argv that opens an installed package: the app itself, or a terminal running the tool. None if not openable."""
    name, kind, _, check, _, cmd = pkg
    check = LAUNCHERS.get(name, check)
    if " " in check or (kind not in ("App", "IDE") and name not in OPEN_IN_TERMINAL):
        return None
    exe = next(filter(None, (shutil.which(c, path=tool_path()) for c in check.split("|"))), None)
    if not exe:
        return None
    if kind in ("App", "IDE"):
        return [exe]
    for term, flag in TERMINALS:
        if term_exe := shutil.which(term, path=tool_path()):
            return [term_exe, flag, "bash", "-c", '"$0"; exec bash', exe]
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
    if name in VERSION_EXE:
        exe = shutil.which(VERSION_EXE[name], path=path) or exe
    if not exe:
        return None
    if name == "Flutter":
        # The snap's flutter downloads a 1.5 GB SDK on first run, so read the version file instead.
        try:
            with open(f"{HOME}/snap/flutter/common/flutter/bin/cache/flutter.version.json") as f:
                return json.load(f).get("frameworkVersion")
        except (OSError, ValueError):
            return None
    try:
        # Own session, so a timeout kills the whole group; otherwise helpers a wrapper starts
        # (downloads, daemons) keep running after we give up on it.
        proc = subprocess.Popen([exe, *VERSION_ARGS.get(check, ["--version"])], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                start_new_session=True)
    except OSError:
        return None
    try:
        out, err = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.communicate()
        return None
    match = re.search(r"\d+\.\d+(\.\d+)?", out + err)
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


def apt_update(pkg):
    """Newer apt version of a package this row installed with apt, or None if apt has nothing newer.
    Asks apt about its own copy, so a tool installed another way (newer gh in ~/.local/bin) isn't flagged."""
    cmd = pkg[5] or ""
    if pkg[0] == "Python tools":
        return None
    for words in re.findall(r"apt-get install -y ((?:[a-z0-9][\w.+-]* ?)+)", cmd):
        for name in words.split():
            if name.startswith("-"):
                continue
            installed, candidate = apt_versions(name)
            if installed and candidate and installed != candidate:
                return candidate
    return None


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


APP_CSS = b"""
/* The state pill on each row: green = here, amber = upgrade waiting, blue = manual download. */
.state {
  border-radius: 999px;
  padding: 3px 11px;
  font-size: 0.85em;
}
.state-plain { background-color: alpha(@theme_fg_color, 0.07); border: 1px solid alpha(@theme_fg_color, 0.14); }
.state-installed { background-color: alpha(#16a34a, 0.18); border: 1px solid alpha(#16a34a, 0.45); }
.state-update { background-color: alpha(#d97706, 0.20); border: 1px solid alpha(#d97706, 0.50); }
.state-manual { background-color: alpha(#2563eb, 0.16); border: 1px solid alpha(#2563eb, 0.42); }

/* Rows: a green wash marks the programs that are already on this PC. */
.row { border-radius: 10px; }
.row-installed { background-color: alpha(#16a34a, 0.08); }
.row:hover { background-color: alpha(@theme_fg_color, 0.06); }
.row-installed:hover { background-color: alpha(#16a34a, 0.14); }

/* Filter chips across the top. */
.chip { border-radius: 999px; padding: 4px 13px; }
.chip-on { background-color: alpha(#0d9488, 0.20); border: 1px solid alpha(#0d9488, 0.55); font-weight: bold; }

/* The little arrow that folds a section away. */
.disclosure { padding: 0 4px; min-width: 0; min-height: 0; }

/* The little summary card in the sidebar. */
.card {
  background-color: alpha(@theme_fg_color, 0.05);
  border: 1px solid alpha(@theme_fg_color, 0.12);
  border-radius: 12px;
  padding: 8px 10px;
}
.group-title { font-size: 0.78em; font-weight: bold; }

/* Progress bars in the brand colour instead of the theme's accent. */
progressbar trough { background-color: alpha(@theme_fg_color, 0.12); border-radius: 5px; }
progressbar progress { background-color: #0d9488; border-radius: 5px; }

/* The little message that appears under the list when something happens. */
.notice {
  background-color: alpha(#0d9488, 0.14);
  border: 1px solid alpha(#0d9488, 0.35);
  border-radius: 8px;
  padding: 6px 12px;
  margin: 4px 12px 2px 12px;
}

/* System info popover pills. */
.pill {
  background-color: alpha(#0d9488, 0.10);
  border: 1px solid alpha(#0d9488, 0.30);
  border-radius: 8px;
  padding: 4px 10px;
}
.pill-key { color: #0d9488; font-weight: bold; font-size: smaller; }
"""

# The four filter chips, in the order they sit in the toolbar.
CHIP_LABELS = {"all": "All", "installed": "Installed", "available": "Not installed", "updates": "Updates"}

# Where a program comes from, shown on the row so it's clear before anything is clicked.
METHOD_TIPS = {
    "apt": "Installed from Ubuntu's own packages (apt).",
    "snap": "Installed as a Snap, so it updates on its own.",
    "flatpak": "Installed as a Flatpak from Flathub.",
    "npm": "Installed with npm, so Node.js is needed first.",
    "deb": "Installed from the maker's own .deb package.",
    "script": "Installed with the maker's own install script.",
    "manual": "No scripted Linux install: the button opens the official page.",
}

# Window size and the last section visited, so the app reopens where you left it.
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", f"{HOME}/.config"), "tux-software-suite")


def load_state():
    """The window size, the last section and the folded sections from the last run."""
    try:
        with open(os.path.join(CONFIG_DIR, "state.json")) as f:
            state = json.load(f)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def save_state(state):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(os.path.join(CONFIG_DIR, "state.json"), "w") as f:
            json.dump(state, f)
    except OSError:
        pass


def install_method(pkg):
    """How this program gets installed: apt, snap, flatpak, npm, deb, script or manual."""
    cmd = pkg[5]
    if cmd is None:
        return "manual"
    if "snap install" in cmd:
        return "snap"
    if "flatpak install" in cmd:
        return "flatpak"
    if "npm install -g" in cmd:
        return "npm"
    if ".deb" in cmd:
        return "deb"
    if "apt-get" in cmd:
        return "apt"
    return "script"


def highlight(text, terms):
    """Escape text for Pango and mark every match of the search words in it."""
    spans, low = [], text.lower()
    for term in terms:
        if len(term) < 2:
            continue  # a single letter would mark half the row
        start = 0
        while (i := low.find(term, start)) != -1:
            spans.append((i, i + len(term)))
            start = i + len(term)
    if not spans:
        return GLib.markup_escape_text(text)
    spans.sort()
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)  # two words overlap, mark them together
        else:
            merged.append([start, end])
    out, last = [], 0
    for start, end in merged:
        out.append(GLib.markup_escape_text(text[last:start]))
        out.append(f"<span background='#fde68a' foreground='#1f2937'>"
                   f"{GLib.markup_escape_text(text[start:end])}</span>")
        last = end
    out.append(GLib.markup_escape_text(text[last:]))
    return "".join(out)


@dataclass
class Row:
    """One program in the list, with the widgets that show it."""
    pkg: tuple
    box: Gtk.Box
    label: Gtk.Label
    state: Gtk.Box
    text: Gtk.Label
    button: Gtk.Button
    opener: Gtk.Button
    check: Gtk.CheckButton
    remove: Gtk.Button
    method: str = ""
    tip: str = ""
    haystack: str = ""
    needs: list = field(default_factory=list)
    can_uninstall: bool = False
    done: bool = False
    version: str = ""
    update: str = ""


@dataclass
class Group:
    """The installed half or the not-installed half of a section."""
    key: str
    title: str
    header: Gtk.Box
    count: Gtk.Label
    rows: list = field(default_factory=list)


@dataclass
class Section:
    """One group of programs in the sidebar: AI apps, Gaming, and so on."""
    name: str
    header: Gtk.Box
    count: Gtk.Label
    tick_all: Gtk.Button
    toggle: Gtk.Button
    rows: list = field(default_factory=list)
    groups: list = field(default_factory=list)
    collapsed: bool = False



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
    return [("TSS", f"v{VERSION}"), ("OS", os_name), ("Kernel", platform.release().split("-")[0]), ("Session", session),
            ("CPU", f"{os.cpu_count()} threads"), ("RAM", ram), ("Free", f"{disk.free // 1024 ** 3} GB"),
            ("GPU", gpu)]


class TuxSoftwareSuite(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Tux Software Suite")
        self.set_icon_name("tux-software-suite")
        self.busy = False
        self.toast_source = 0
        self.rows = []
        self.sections = []
        self.done = {pkg[0]: False for pkg in PACKAGES}
        self.updates = set()
        self.state_filter = "all"
        self.section_filter = "All"
        self.sysinfo = []
        self.last_terms = []
        self.scans = 0  # how many version scans are running

        saved = load_state()
        size = saved.get("size")
        if isinstance(size, list) and len(size) == 2 and all(isinstance(v, int) for v in size):
            width, height = size
            # Ignore a size that is too small to be usable (a window saved before it was shown).
            if width >= 800 and height >= 600:
                self.set_default_size(width, height)
        if saved.get("section") in [s for s, _ in SECTIONS] + ["All"]:
            self.section_filter = saved["section"]
        folded = saved.get("collapsed")
        collapsed = set(folded) if isinstance(folded, list) else set()

        css = Gtk.CssProvider()
        css.load_from_data(APP_CSS, -1)
        Gtk.StyleContext.add_provider_for_display(self.get_display(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Program list: sections, each split into an installed half and a not-installed half.
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                                margin_top=2, margin_bottom=12, margin_start=12, margin_end=12)
        for name, pkgs in SECTIONS:
            header, count, tick_all, toggle = self.make_section_header(name)
            section = Section(name=name, header=header, count=count, tick_all=tick_all, toggle=toggle,
                              collapsed=name in collapsed)
            for key, title in (("installed", "Installed"), ("available", "Not installed")):
                gheader, glabel = self.make_group_header(title)
                section.groups.append(Group(key=key, title=title, header=gheader, count=glabel))
            self.sections.append(section)
            for pkg in pkgs:
                row = self.add_row(pkg)
                section.rows.append(row)
                self.rows.append(row)

        list_scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                           kinetic_scrolling=True, overlay_scrolling=True)
        list_scroller.set_child(self.list_box)
        self.list_scroller = list_scroller

        # Toolbar: search and quick picks.
        self.search = Gtk.SearchEntry(placeholder_text="Search programs…", hexpand=True, width_chars=12)
        self.search.connect("search-changed", self.on_filter)
        self.search.set_key_capture_widget(self)  # just start typing anywhere to filter
        presets_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=4, margin_bottom=4)
        popover = Gtk.Popover(child=presets_box)
        for label, names in PRESETS:
            btn = Gtk.Button(label=label, halign=Gtk.Align.FILL)
            btn.add_css_class("flat")
            btn.connect("clicked", lambda _b, n=names, p=popover: (p.popdown(), self.tick(n)))
            presets_box.append(btn)
        quick = Gtk.MenuButton(label="Quick picks", popover=popover,
                               tooltip_text="Tick a ready-made set of programs, then press Install")
        toolbar = Gtk.Box(spacing=6, margin_top=8, margin_bottom=4, margin_start=12, margin_end=12)
        toolbar.append(self.search)
        toolbar.append(quick)

        # Filter chips: one click to see what is installed, what is missing or what needs updating.
        chip_box = Gtk.Box(spacing=4)
        self.chips = {}
        for key, label in CHIP_LABELS.items():
            btn = Gtk.Button(label=label)
            btn.add_css_class("chip")
            btn.connect("clicked", lambda _b, k=key: self.set_state_filter(k))
            self.chips[key] = btn
            chip_box.append(btn)

        self.update_all = Gtk.Button(label="Update all", visible=False,
                                     tooltip_text="Upgrade every program marked ⬆ with one password prompt")
        self.update_all.connect("clicked", self.on_update_all)
        self.install_selected = Gtk.Button(label="Install", sensitive=False,
                                           tooltip_text="Install every ticked program")
        self.install_selected.add_css_class("suggested-action")
        self.install_selected.connect("clicked", self.on_install_selected)
        self.clear = Gtk.Button(icon_name="edit-clear-symbolic", tooltip_text="Untick everything", visible=False)
        self.clear.add_css_class("flat")
        self.clear.connect("clicked", self.on_clear_selection)
        filter_bar = Gtk.Box(spacing=6, margin_top=2, margin_bottom=4, margin_start=12, margin_end=12)
        filter_bar.append(chip_box)
        filter_bar.append(Gtk.Box(hexpand=True))  # spacer
        filter_bar.append(self.update_all)
        filter_bar.append(self.install_selected)
        filter_bar.append(self.clear)

        # A slim strip that always says how much of the list is already on this PC.
        self.summary = Gtk.Label(xalign=0)
        self.summary.add_css_class("dim-label")
        self.summary_bar = Gtk.ProgressBar(hexpand=False, width_request=150, valign=Gtk.Align.CENTER)
        self.summary_updates = Gtk.Label(xalign=1, hexpand=True)
        self.summary_updates.add_css_class("dim-label")
        self.collapse_all = Gtk.Button(label="Collapse all", valign=Gtk.Align.CENTER)
        self.collapse_all.add_css_class("flat")
        self.collapse_all.set_tooltip_text("Fold every section away, or open them all again")
        self.collapse_all.connect("clicked", self.on_collapse_all)
        summary = Gtk.Box(spacing=8, margin_start=12, margin_end=12, margin_bottom=6)
        summary.append(self.summary)
        summary.append(self.summary_bar)
        summary.append(self.summary_updates)
        summary.append(self.collapse_all)

        # Shown when a filter leaves nothing on screen.
        self.empty_label = Gtk.Label(xalign=0, hexpand=True)
        self.empty_label.add_css_class("dim-label")
        clear_filters = Gtk.Button(label="Clear search and filters")
        clear_filters.add_css_class("flat")
        clear_filters.connect("clicked", self.on_clear_filters)
        self.empty_bar = Gtk.Box(spacing=8, margin_start=12, margin_end=12, margin_top=8)
        self.empty_bar.append(self.empty_label)
        self.empty_bar.append(clear_filters)
        self.empty_bar.set_visible(False)

        # Sidebar: a summary card, then the sections with their counts.
        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav.add_css_class("navigation-sidebar")
        self.nav_counts = {}
        for section in ["All sections"] + [s for s, _ in SECTIONS]:
            name = Gtk.Label(label=section, xalign=0, hexpand=True, ellipsize=3)
            count = Gtk.Label()
            count.add_css_class("dim-label")
            self.nav_counts[section] = count
            box = Gtk.Box(spacing=6, margin_start=6, margin_end=6, margin_top=3, margin_bottom=3)
            box.append(name)
            box.append(count)
            row = Gtk.ListBoxRow(child=box)
            row.section = "All" if section == "All sections" else section
            self.nav.append(row)
        self.nav.connect("row-selected", self.on_nav)
        nav_scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        nav_scroller.set_child(self.nav)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=10, margin_end=10,
                       margin_top=2)
        card.add_css_class("card")
        self.card_count = Gtk.Label(xalign=0)
        self.card_bar = Gtk.ProgressBar(hexpand=True, valign=Gtk.Align.CENTER, height_request=8)
        self.card_hint = Gtk.Label(xalign=0, wrap=True)
        self.card_hint.add_css_class("dim-label")
        card.append(self.card_count)
        card.append(self.card_bar)
        card.append(self.card_hint)

        self.pills = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        copy_info = Gtk.Button(label="Copy system info", tooltip_text="For a bug report or forum post")
        copy_info.connect("clicked", lambda _b: self.get_clipboard().set(
            "\n".join(f"{k}: {v}" for k, v in self.sysinfo)))
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=8, margin_bottom=8,
                           margin_start=8, margin_end=8)
        info_box.append(self.pills)
        info_box.append(copy_info)
        info_button = Gtk.MenuButton(label=f"System info · v{VERSION}", popover=Gtk.Popover(child=info_box),
                                     direction=Gtk.ArrowType.UP, margin_start=6, margin_end=6, margin_bottom=6)
        info_button.add_css_class("flat")
        threading.Thread(target=lambda: GLib.idle_add(self.show_pills, system_info()), daemon=True).start()

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, width_request=215)
        brand = Gtk.Label(xalign=0, margin_start=12, margin_top=12)
        brand.set_markup("<span size='large' foreground='#0d9488'><b>Tux Software Suite</b></span>")
        sidebar.append(brand)
        sidebar.append(card)
        sidebar.append(nav_scroller)
        sidebar.append(info_button)

        # Log: a slim bar that expands when a job runs.
        self.log = Gtk.TextView(editable=False, monospace=True, cursor_visible=False,
                                left_margin=12, right_margin=12, top_margin=6, bottom_margin=6)
        self.log_scroller = Gtk.ScrolledWindow(vexpand=True, min_content_height=60)
        self.log_scroller.set_child(self.log)
        log_bar = Gtk.Box(spacing=6)
        self.log_toggle = Gtk.ToggleButton(label="▸ Log", active=False, halign=Gtk.Align.START, hexpand=True,
                                           margin_start=6, tooltip_text="Hide or show the log")
        self.log_toggle.add_css_class("flat")
        self.log_toggle.connect("toggled", self.on_log_toggle)
        log_bar.append(self.log_toggle)
        for label, handler in (("Recheck", lambda _b: self.refresh()),
                               ("Copy log", self.on_copy_log), ("Clear log", self.on_clear_log)):
            btn = Gtk.Button(label=label)
            btn.add_css_class("flat")
            btn.connect("clicked", handler)
            log_bar.append(btn)
        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bottom.append(Gtk.Separator())
        # A one-line notice that appears when something worth knowing happens.
        self.notice = Gtk.Label(xalign=0, hexpand=True)
        self.notice.add_css_class("notice")
        self.notice_row = Gtk.Box()
        self.notice_row.append(self.notice)
        self.notice_row.set_visible(False)
        bottom.append(self.notice_row)
        bottom.append(log_bar)
        bottom.append(self.log_scroller)
        self.log_scroller.set_visible(False)

        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        top.append(toolbar)
        top.append(filter_bar)
        top.append(summary)
        top.append(self.empty_bar)
        top.append(list_scroller)
        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL, vexpand=True, hexpand=True)
        paned.set_start_child(top)
        paned.set_end_child(bottom)
        paned.set_shrink_start_child(True)
        paned.set_shrink_end_child(False)
        paned.set_resize_end_child(False)
        self.paned = paned
        self.log_position = 460

        main = Gtk.Box()
        main.append(sidebar)
        main.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        main.append(paned)
        self.set_child(main)

        self.connect("close-request", self.on_close)
        self.add_shortcuts()
        self.select_section(self.section_filter)
        self.set_state_filter(self.state_filter)
        self.refresh()

    def make_section_header(self, name):
        """The teal heading of a section, with its counts and a shortcut to tick the whole section."""
        header = Gtk.Box(spacing=8, margin_top=16, margin_bottom=2)
        toggle = Gtk.Button(valign=Gtk.Align.CENTER)
        toggle.add_css_class("flat")
        toggle.add_css_class("disclosure")
        toggle.set_icon_name("pan-down-symbolic")
        toggle.set_tooltip_text("Collapse or expand this section")
        toggle.connect("clicked", lambda _b, n=name: self.toggle_section(n))
        title = Gtk.Label(xalign=0, hexpand=True)
        title.set_markup(f"<span size='large' foreground='#0d9488'><b>"
                         f"{GLib.markup_escape_text(name.upper())}</b></span>")
        count = Gtk.Label(xalign=1, valign=Gtk.Align.CENTER)
        count.add_css_class("dim-label")
        tick_all = Gtk.Button(label="Tick all", valign=Gtk.Align.CENTER)
        tick_all.add_css_class("flat")
        tick_all.set_tooltip_text("Tick every program in this section that isn't installed yet")
        tick_all.connect("clicked", lambda _b, n=name: self.tick_section(n))
        header.append(toggle)
        header.append(title)
        header.append(count)
        header.append(tick_all)
        return header, count, tick_all, toggle

    def make_group_header(self, title):
        """The small 'Installed' / 'Not installed' heading that splits a section in two."""
        header = Gtk.Box(spacing=8, margin_top=10, margin_bottom=1)
        label = Gtk.Label(xalign=0, hexpand=True)
        label.add_css_class("group-title")
        header.append(label)
        return header, label

    def add_shortcuts(self):
        """Keyboard shortcuts for the things that get done most often."""
        actions = {
            "search": lambda: self.search.grab_focus(),
            "recheck": lambda: self.refresh(),
            "install-selected": lambda: self.on_install_selected(None),
            "update-all": lambda: self.on_update_all(None),
        }
        for name, action in actions.items():
            simple = Gio.SimpleAction.new(name, None)
            simple.connect("activate", lambda _a, _p, f=action: f())
            self.add_action(simple)
        app = self.get_application()
        for name, keys in (("search", ["<Control>f"]), ("recheck", ["<Control>r"]),
                           ("install-selected", ["<Control>i"]), ("update-all", ["<Control>u"])):
            app.set_accels_for_action(f"win.{name}", keys)

    def on_close(self, _window):
        width, height = self.get_width(), self.get_height()
        state = {"section": self.section_filter,
                 "collapsed": [s.name for s in self.sections if s.collapsed]}
        if width >= 800 and height >= 600:
            state["size"] = [width, height]
        save_state(state)
        return False

    def toast(self, text):
        """A short message that appears under the list and fades away again."""
        self.notice.set_text(text)
        self.notice_row.set_visible(True)
        if self.toast_source:
            GLib.source_remove(self.toast_source)
        self.toast_source = GLib.timeout_add(3500, self.hide_toast)

    def hide_toast(self):
        self.notice_row.set_visible(False)
        self.toast_source = 0
        return False

    def add_row(self, pkg):
        name, kind, desc, _check, url, cmd = pkg
        tip = TIPS.get(name, "")
        method = install_method(pkg)

        # The text of a row is rebuilt whenever the search or the install state changes.
        label = Gtk.Label(xalign=0, hexpand=True, wrap=True, width_chars=18, max_width_chars=90)

        # The pill says at a glance whether the program is here, missing or upgradable.
        text = Gtk.Label(xalign=0, ellipsize=3, max_width_chars=14)
        state = Gtk.Box(spacing=4, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        state.add_css_class("state")
        state.add_css_class("state-plain")
        state.append(text)

        button = Gtk.Button(label="Install", width_request=96, valign=Gtk.Align.CENTER)
        button.connect("clicked", self.on_install, pkg)
        opener = Gtk.Button(label="Open", visible=False, tooltip_text="Launch it", valign=Gtk.Align.CENTER)
        opener.add_css_class("suggested-action")
        opener.connect("clicked", self.on_open, pkg)

        # Rarely used actions live in a ⋮ menu so each row stays narrow.
        copy = Gtk.Button(label="Copy link", tooltip_text=url)
        copy.add_css_class("flat")
        copy.connect("clicked", self.on_copy, name, url)
        copy_cmd = Gtk.Button(label="Copy command", tooltip_text=cmd or "Opens the download page")
        copy_cmd.add_css_class("flat")
        copy_cmd.connect("clicked", self.on_copy_command, pkg)
        remove_cmd = uninstall_command(pkg)
        remove = Gtk.Button(label="Uninstall…", visible=False, tooltip_text=f"Runs: {remove_cmd}")
        remove.add_css_class("flat")
        remove.add_css_class("error")
        remove.connect("clicked", self.on_uninstall, name, remove_cmd)
        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        menu_box.append(copy)
        menu_box.append(copy_cmd)
        menu_box.append(remove)
        # The popover is built when first opened; 140 of them at startup made scrolling stutter.
        more = Gtk.MenuButton(icon_name="view-more-symbolic", valign=Gtk.Align.CENTER, tooltip_text="More")
        popover = Gtk.Popover(child=menu_box)
        for b in (copy, copy_cmd, remove):
            b.connect("clicked", lambda _b, p=popover: p.popdown())
        more.set_create_popup_func(lambda m, p=popover: m.set_popover(p))
        more.add_css_class("flat")

        # Download-only entries can't be batch installed, so their checkbox is greyed out.
        check = Gtk.CheckButton(valign=Gtk.Align.CENTER, sensitive=cmd is not None,
                                tooltip_text="Tick to install several at once")
        check.connect("toggled", lambda _c: self.update_selection())

        box = Gtk.Box(spacing=8, margin_top=3, margin_bottom=3)
        box.add_css_class("row")
        for widget in (check, label, state, opener, button, more):
            box.append(widget)
        row = Row(pkg=pkg, box=box, label=label, state=state, text=text, button=button,
                  opener=opener, check=check, remove=remove, method=method, tip=tip,
                  haystack=" ".join(pkg[:3]).lower(),  # what the search box looks in
                  needs=self.missing_prerequisites(pkg), can_uninstall=remove_cmd is not None)
        label.set_markup(self.row_markup(row))
        label.set_tooltip_text(self.row_tooltip(row))
        return row

    def row_markup(self, row, terms=()):
        """The text of a row: name, kind, how it gets installed and what it needs first."""
        name, kind, desc = row.pkg[0], row.pkg[1], row.pkg[2]
        markup = (f"<b>{highlight(name, terms)}</b>  "
                  f"<span size='small' foreground='#0d9488'><b>{GLib.markup_escape_text(kind)}</b></span>  "
                  f"<span size='small' foreground='#8a8a8a'>{row.method}</span>")
        if row.needs:
            markup += (f"  <span size='small' foreground='#b45309'>needs "
                       f"{GLib.markup_escape_text(', '.join(row.needs))}</span>")
        markup += f"\n<small>{highlight(desc, terms)}</small>"
        if row.tip:
            markup += f"\n<small><i>💡 {highlight(row.tip, terms)}</i></small>"
        return markup

    def row_tooltip(self, row):
        """Hovering a name shows where it comes from, what it runs and what it needs first."""
        url, cmd = row.pkg[4], row.pkg[5]
        tip = f"Source: {url}\n"
        tip += f"Runs: {cmd}" if cmd else "Opens the download page"
        if row.tip:
            tip += f"\nTip: {row.tip}"
        tip += f"\nHow: {METHOD_TIPS[row.method]}"
        if row.needs:
            tip += f"\nNeeds first: {', '.join(row.needs)} (installed automatically)"
        return tip

    def missing_prerequisites(self, pkg):
        """Programs this one needs first that aren't on this PC yet."""
        return [name for name in prerequisites(pkg) if name in PACKAGE_NAMES and not self.done.get(name)]

    def update_needs(self, row):
        """Note what a program needs first; redraw the row only when that changed."""
        needs = self.missing_prerequisites(row.pkg)
        if needs != row.needs:
            row.needs = needs
            row.label.set_markup(self.row_markup(row, self.last_terms))
            row.label.set_tooltip_text(self.row_tooltip(row))

    def search_terms(self):
        """The words typed in the search box, lower case and without the empty ones."""
        return self.search.get_text().strip().lower().split()

    def assign_groups(self):
        """Put every row in the installed or the not-installed half of its section."""
        for section in self.sections:
            for group in section.groups:
                group.rows = [r for r in section.rows if r.done == (group.key == "installed")]

    def layout(self):
        """Lay out each section with the installed programs first, then the rest, each part A–Z."""
        # Re-ordering only when the order really changed keeps the scroll position where the user left it.
        order = []
        for section in self.sections:
            order.append(section.header)
            for group in section.groups:
                if not group.rows:
                    continue
                order.append(group.header)
                order += [r.box for r in sorted(group.rows, key=lambda r: r.pkg[0].lower())]
        if order == getattr(self, "shown_order", None):
            return
        self.shown_order = order
        adjustment = self.list_scroller.get_vadjustment()
        top = adjustment.get_value()
        for child in list(self.list_box):
            self.list_box.remove(child)
        for widget in order:
            self.list_box.append(widget)
        GLib.idle_add(adjustment.set_value, top)

    def refresh(self):
        self.updates.clear()  # found again by load_versions below
        for row in self.rows:
            self.done[row.pkg[0]] = is_installed(row.pkg[3])
        for row in self.rows:
            row.done = self.done[row.pkg[0]]
            self.apply_state(row)
            self.update_needs(row)
        self.assign_groups()
        self.update_counts()
        self.update_selection()
        self.layout()
        self.apply_filter()
        # Asking each tool for its version is slow, so do it off the UI thread.
        self.scans += 1
        self.update_chip_counts()  # the update count is unknown until the scan is done
        threading.Thread(target=self.load_versions, daemon=True).start()

    def apply_state(self, row):
        """Draw one row to match what is (or isn't) on this PC."""
        pkg = row.pkg
        done = self.done[pkg[0]]
        manual = pkg[5] is None
        row.button.remove_css_class("suggested-action")
        row.button.set_label("Reinstall" if done else ("Download" if manual else "Install"))
        row.button.set_sensitive(not self.busy)
        row.remove.set_visible(done and row.can_uninstall)
        row.remove.set_sensitive(not self.busy)
        row.opener.set_visible(done and launch_command(pkg) is not None)
        row.check.set_sensitive(not manual and not self.busy)
        row.box.remove_css_class("row-installed")
        row.box.remove_css_class("row-available")
        row.box.add_css_class("row-installed" if done else "row-available")
        if done:
            self.set_state(row, "✓ installed", "Installed on this PC", "state-installed")
        elif manual:
            self.set_state(row, "⇩ download",
                           "No scripted Linux install: the button opens the official page", "state-manual")
        else:
            self.set_state(row, "⬇ not installed", "Not installed on this PC", "state-plain")

    @staticmethod
    def set_state(row, text, tooltip, style):
        row.text.set_text(text)
        row.text.set_tooltip_text(tooltip)
        for name in ("state-plain", "state-installed", "state-update", "state-manual"):
            row.state.remove_css_class(name)
        row.state.add_css_class(style)

    def load_versions(self):
        """Show the installed version, or the version Install will get, and flag apt updates."""
        # Each lookup can take seconds (snap and npm ask the network), so run them side by side.
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(self.load_version, self.rows))
        GLib.idle_add(self.scan_finished)

    def scan_finished(self):
        """The background scan is done, so the update count and the list are final."""
        self.scans = max(0, self.scans - 1)
        self.update_counts()
        self.apply_filter()
        return False

    def load_version(self, row):
        pkg = row.pkg
        if self.done.get(pkg[0]):
            version = installed_version(pkg)
            newer = apt_update(pkg)
            if version and newer:
                self.updates.add(pkg[0])
                GLib.idle_add(self.set_installed_state, row, version, newer)
            elif version:
                GLib.idle_add(self.set_installed_state, row, version, None)
        elif pkg[5] is not None:
            version = available_version(pkg)
            GLib.idle_add(self.set_available_state, row, version)

    def set_installed_state(self, row, version, newer):
        if newer:
            self.set_state(row, f"⬆ {newer}",
                           f"Installed {version}; {newer} is available (press Update)", "state-update")
            row.button.set_label("Update")
            row.button.add_css_class("suggested-action")
        else:
            self.set_state(row, f"✓ {version}", f"Installed version {version}", "state-installed")
        self.update_chip_counts()
        return False

    def set_available_state(self, row, version):
        if version == "latest":
            self.set_state(row, "⬇ latest",
                           "The maker's installer always fetches their newest release", "state-plain")
        elif version:
            self.set_state(row, f"⬇ {version}", f"Install will get version {version}", "state-plain")
        else:
            self.set_state(row, "⬇ not installed", "Not installed on this PC", "state-plain")
        return False

    def update_counts(self):
        """Refresh every number on screen: sidebar, chips and section headings."""
        installed = sum(1 for r in self.rows if r.done)
        total = len(self.rows)
        self.card_count.set_text(f"{installed} installed")
        self.card_bar.set_fraction(installed / total if total else 0)
        hints = [f"{total - installed} not installed"]
        if self.updates:
            hints.append(f"{len(self.updates)} update{'s' if len(self.updates) > 1 else ''} available")
        self.card_hint.set_text(" · ".join(hints))
        self.summary.set_text(f"{installed} of {total} installed")
        self.summary_bar.set_fraction(installed / total if total else 0)
        self.summary_updates.set_text(f"{len(self.updates)} update{'s' if len(self.updates) != 1 else ''} available"
                                      if self.updates else "")
        self.update_chip_counts()
        self.nav_counts["All sections"].set_markup(
            f"<span foreground='#16a34a'>{installed}</span>/{total}")
        for section in self.sections:
            got = sum(1 for r in section.rows if r.done)
            self.nav_counts[section.name].set_markup(
                f"<span foreground='#16a34a'>{got}</span>/{len(section.rows)}")
            section.count.set_markup(
                f"<span foreground='#16a34a'>{got} installed</span> · {len(section.rows) - got} not installed")
            section.tick_all.set_sensitive(not self.busy and any(not r.done for r in section.rows))
            for group in section.groups:
                group.count.set_markup(self.group_markup(group, len(group.rows)))

    @staticmethod
    def group_markup(group, count):
        colour = "#16a34a" if group.key == "installed" else "#7a7a7a"
        mark = "✓" if group.key == "installed" else "⬇"
        return (f"<span foreground='{colour}'>{mark} {group.title.upper()}</span> "
                f"<span foreground='#8a8a8a'>· {count}</span>")

    def update_chip_counts(self):
        installed = sum(1 for r in self.rows if r.done)
        total = len(self.rows)
        counts = {"all": total, "installed": installed, "available": total - installed,
                  "updates": len(self.updates)}
        for key, count in counts.items():
            # While the first scan runs there is nothing to show yet, so say that it is looking.
            label = (f"{CHIP_LABELS[key]} …" if key == "updates" and not count and self.scans
                     else f"{CHIP_LABELS[key]} {count}")
            if self.chips[key].get_label() != label:  # setting it again would move the toolbar
                self.chips[key].set_label(label)

    def show_pills(self, info):
        self.sysinfo = info
        for key, value in info:
            pill = Gtk.Box(spacing=8)
            pill.add_css_class("pill")
            k = Gtk.Label(label=key.upper(), width_chars=7, xalign=0)
            k.add_css_class("pill-key")
            pill.append(k)
            pill.append(Gtk.Label(label=value, xalign=0, wrap=True, max_width_chars=40, selectable=True))
            self.pills.append(pill)
        return False

    def selected(self):
        return [row.pkg for row in self.rows if row.check.get_active()]

    def update_selection(self):
        count = len(self.selected())
        self.install_selected.set_label(f"Install {count}" if count else "Install")
        self.clear.set_visible(count > 0)
        self.install_selected.set_sensitive(count > 0 and not self.busy)
        self.update_all.set_label(f"Update all ({len(self.updates)})")
        self.update_all.set_visible(bool(self.updates))
        self.update_all.set_sensitive(not self.busy)
        return False

    def set_state_filter(self, key):
        """Show everything, or only what is installed, missing or upgradable."""
        self.state_filter = key
        for name, btn in self.chips.items():
            if name == key:
                btn.add_css_class("chip-on")
            else:
                btn.remove_css_class("chip-on")
        self.apply_filter()

    def tick(self, names):
        """Tick the not-yet-installed programs from a Quick picks set and show what was chosen."""
        self.set_state_filter("all")
        count = 0
        for row in self.rows:
            if row.pkg[0] in names and not row.done and row.pkg[5] is not None:
                row.check.set_active(True)
                count += 1
        self.append(f"\nTicked {count} not-yet-installed programs. Press Install to get them.\n")
        self.toast(f"Ticked {count} programs")

    def tick_section(self, name):
        """Tick everything in one section that isn't installed yet."""
        section = next(s for s in self.sections if s.name == name)
        count = 0
        for row in section.rows:
            if not row.done and row.pkg[5] is not None:
                row.check.set_active(True)
                count += 1
        self.set_state_filter("all")
        self.toast(f"Ticked {count} programs in {name}")

    def on_clear_selection(self, _button):
        for row in self.rows:
            row.check.set_active(False)

    def on_clear_filters(self, _button):
        self.search.set_text("")
        self.set_state_filter("all")
        self.select_section("All")

    def select_section(self, name):
        """Show one section of the sidebar, or all of them."""
        self.section_filter = name
        index = 0 if name == "All" else [s for s, _ in SECTIONS].index(name) + 1
        self.nav.select_row(self.nav.get_row_at_index(index))
        self.apply_filter()
        self.list_scroller.get_vadjustment().set_value(0)

    def on_nav(self, _listbox, row):
        if row is not None:
            self.section_filter = row.section
            self.apply_filter()
            self.list_scroller.get_vadjustment().set_value(0)

    def on_filter(self, _entry):
        self.apply_filter()

    def matches(self, row, section, terms):
        """True when a row survives the current section, state and text filters."""
        pkg = row.pkg
        if self.section_filter not in ("All", section.name):
            return False
        if self.state_filter == "installed" and not row.done:
            return False
        if self.state_filter == "available" and row.done:
            return False
        if self.state_filter == "updates" and pkg[0] not in self.updates:
            return False
        # Every word typed has to appear somewhere in the program's name, kind or description.
        return all(term in row.haystack for term in terms)

    def apply_filter(self):
        terms = self.search_terms()
        changed = terms != self.last_terms
        self.last_terms = terms
        rows = 0
        sections = 0
        for section in self.sections:
            # A search opens every section, so nothing stays hidden while you are typing.
            folded = section.collapsed and not terms
            section_shown = False
            for group in section.groups:
                group_shown = False
                for row in group.rows:
                    shown = self.matches(row, section, terms)
                    section_shown |= shown
                    group_shown |= shown
                    visible = shown and not folded
                    was = row.box.get_visible()
                    if was != visible:  # only a change asks the window to lay out again
                        row.box.set_visible(visible)
                    rows += visible
                    # Only the rows on screen are drawn again, and only when the search moved.
                    if visible and (changed or not was):
                        row.label.set_markup(self.row_markup(row, terms))
                if group.header.get_visible() != (group_shown and not folded):
                    group.header.set_visible(group_shown and not folded)
            # The heading stays even when the section is folded, otherwise it could not be opened.
            if section.header.get_visible() != section_shown:
                section.header.set_visible(section_shown)
            sections += section_shown
        # The empty message is only for when there is nothing at all; folded sections still count.
        self.empty_bar.set_visible(sections == 0)
        if not sections:
            if terms:
                self.empty_label.set_text(f"No program matches “{self.search.get_text().strip()}”.")
            elif self.state_filter == "updates" and self.scans:
                self.empty_label.set_text("Still looking for updates…")
            else:
                self.empty_label.set_text("Nothing to show here.")
        self.update_chip_counts()  # the chips carry the same numbers as the list
        self.sync_toggles()
        return False

    def sync_toggles(self):
        """Keep the fold arrows and the fold-all button in step with the sections."""
        searching = bool(self.search.get_text().strip())
        for section in self.sections:
            section.toggle.set_icon_name("pan-end-symbolic" if section.collapsed and not searching
                                         else "pan-down-symbolic")
        self.collapse_all.set_label("Expand all" if all(s.collapsed for s in self.sections) else "Collapse all")

    def toggle_section(self, name):
        """Fold a section away or open it again."""
        section = next(s for s in self.sections if s.name == name)
        # While a search is running everything is open, so the arrow shows the section as open.
        open_now = not (section.collapsed and not self.search.get_text().strip())
        section.collapsed = open_now
        self.search.set_text("")  # a search opens everything, so drop it before folding
        self.apply_filter()

    def on_collapse_all(self, _button):
        """Fold every section away, or open them all again."""
        fold = not all(s.collapsed for s in self.sections)
        for section in self.sections:
            section.collapsed = fold
        self.search.set_text("")
        self.apply_filter()

    def on_log_toggle(self, button):
        """Collapse the log down to its title bar, or bring it back at its old size."""
        show = button.get_active()
        button.set_label(("▾" if show else "▸") + " Log")
        if not show:
            self.log_position = self.paned.get_position()
        self.log_scroller.set_visible(show)
        height = self.paned.get_height() or 600
        # An oversized position is clamped, so the list takes all the room the log gave up.
        self.paned.set_position(min(self.log_position, height - 160) if show else 100000)

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
        self.toast(f"Copied the link for {name}")

    def on_copy_command(self, _button, pkg):
        """Put the exact command this program would run on the clipboard."""
        name, cmd = pkg[0], pkg[5]
        if not cmd:
            self.toast(f"{name} has no install command: it opens the download page")
            return
        self.get_clipboard().set(cmd)
        self.append(f"Copied {name} command: {cmd}\n")
        self.toast(f"Copied the install command for {name}")

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
        self.install_many([pkg], "Installing", "")

    def on_install_selected(self, _button):
        self.install_many(self.selected(), "Installing", "selected")
        self.on_clear_selection(None)

    def on_update_all(self, _button):
        # Only apt programs are ever marked as updates, and installing one again upgrades it.
        self.install_many([row.pkg for row in self.rows if row.pkg[0] in self.updates], "Updating", "outdated")

    def with_prerequisites(self, pkgs):
        """pkgs plus anything they need that isn't installed yet, needed ones first."""
        by_name = {p[0]: p for p in PACKAGES}
        ordered = []

        def add(pkg, trail=()):
            if pkg in ordered or pkg[0] in trail:
                return
            for need in prerequisites(pkg):
                if need in by_name and not self.done.get(need):
                    add(by_name[need], trail + (pkg[0],))
            ordered.append(pkg)

        for pkg in pkgs:
            add(pkg)
        return ordered

    def install_many(self, pkgs, verb, what):
        chosen = pkgs
        pkgs = self.with_prerequisites(pkgs)
        extra = [p[0] for p in pkgs if p not in chosen]
        # Plain apt installs are merged into one command, so there's one password prompt for all of them.
        # They run first, which is also right for prerequisites (Essentials, Node.js, Neovim are apt).
        apt_pkgs, jobs = [], []
        for pkg in pkgs:
            if match := APT_ONLY.match(pkg[5] or ""):
                apt_pkgs.append((pkg[0], match.group(1)))
            elif pkg[5]:
                jobs.append((f"{verb} {pkg[0]}", pkg[5]))
        if apt_pkgs:
            names = ", ".join(name for name, _ in apt_pkgs)
            jobs.insert(0, (f"{verb} {names}", with_apt_update(apt(*(p for _, p in apt_pkgs)))))
        elif jobs:
            jobs[0] = (jobs[0][0], with_apt_update(jobs[0][1]))
        if extra:
            self.append(f"\nAlso installing what they need first: {', '.join(extra)}\n")
        if len(pkgs) > 1:
            self.append(f"\n### {verb} {len(pkgs)}{' ' + what if what else ''}: {', '.join(p[0] for p in pkgs)} ###\n")
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
        self.total = len(jobs)
        self.failed = []
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
        if not online():
            GLib.idle_add(self.append, "\nNo internet connection. Connect to Wi-Fi or plug in a cable, then try again.\n")
            GLib.idle_add(self.finish, f"=== {name}: FAILED (offline) ===\n", name)
            return
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
        GLib.idle_add(self.finish, f"=== {name}: {result} ===\n", None if code == 0 else name)

    def finish(self, msg, failed):
        self.append(msg)
        if failed:
            self.failed.append(failed)
        if self.queue:
            self.refresh()
            return self.run_next()
        if self.total > 1:
            # A long batch scrolls past its failures, so say at the end what needs another look.
            self.append(f"\n### {self.total - len(self.failed)} of {self.total} steps done"
                        + (f"; FAILED: {'; '.join(self.failed)}" if self.failed else " ✓") + " ###\n")
        self.busy = False
        self.refresh()
        if self.total:
            # Say how it went in a toast too, so the answer is visible without reading the log.
            done = self.total - len(self.failed)
            self.toast(f"{done} of {self.total} done ✓" if not self.failed
                       else f"{done} of {self.total} done · {len(self.failed)} failed")
        return False


def main():
    app = Gtk.Application(application_id="local.tuxsoftwaresuite")
    app.connect("activate", lambda a: TuxSoftwareSuite(a).present())
    app.run(None)


if __name__ == "__main__":
    main()
