# ~/.zshrc

# -----------------------------
# PATH
# -----------------------------

typeset -U path PATH
path=("$HOME/.local/bin" $path)
export PATH


# -----------------------------
# History
# -----------------------------

HISTFILE="$HOME/.zsh_history"
HISTSIZE=50000
SAVEHIST=50000

setopt EXTENDED_HISTORY
setopt HIST_IGNORE_DUPS
setopt HIST_IGNORE_ALL_DUPS
setopt HIST_IGNORE_SPACE
setopt HIST_REDUCE_BLANKS
setopt HIST_VERIFY
setopt SHARE_HISTORY
setopt APPEND_HISTORY


# -----------------------------
# Shell behavior
# -----------------------------

setopt AUTO_CD
setopt AUTO_PUSHD
setopt PUSHD_IGNORE_DUPS
setopt PUSHD_SILENT
setopt INTERACTIVE_COMMENTS

# Optional. Useful, but can be noisy.
# setopt CORRECT

# Disable flow control so Ctrl-S works in terminal apps/search.
stty -ixon


# -----------------------------
# Completion
# -----------------------------

autoload -Uz compinit

# Let `cd -<TAB>` complete cd's own options (-L/-P). Only the _cd completer
# consults this style; option completion for other commands is automatic.
zstyle ':completion:*' complete-options true

# Show descriptions/groups in completion menu.
zstyle ':completion:*' verbose true
zstyle ':completion:*:descriptions' format '%F{yellow}%d%f'
zstyle ':completion:*' group-name ''
zstyle ':completion:*' use-cache on
zstyle ':completion:*' cache-path "$HOME/.zcompcache"

compinit -d "$HOME/.zcompdump"

zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Z}'
zstyle ':completion:*' squeeze-slashes true
zstyle ':completion:*' special-dirs true

# Use LS_COLORS for completion colors when available.
if [[ -n "$LS_COLORS" ]]; then
  zstyle ':completion:*' list-colors "${(s.:.)LS_COLORS}"
fi


# -----------------------------
# Colors
# -----------------------------

autoload -Uz colors && colors

# -----------------------------
# mise
# -----------------------------

if command -v mise >/dev/null 2>&1; then
  eval "$(mise activate zsh)"
fi

# -----------------------------
# fzf
# -----------------------------

if command -v fzf >/dev/null 2>&1; then
  export FZF_DEFAULT_OPTS='--height 40% --layout=reverse --border'
fi


# -----------------------------
# Editor
# -----------------------------

if command -v nvim >/dev/null 2>&1; then
  export EDITOR='nvim'
  export VISUAL='nvim'
else
  export EDITOR='vim'
  export VISUAL='vim'
fi


# -----------------------------
# Aliases
# -----------------------------

if command -v eza >/dev/null 2>&1; then
  alias ls='eza --icons=auto --group-directories-first'
  alias ll='eza -lah --icons=auto --group-directories-first --git'
  alias la='eza -A --icons=auto --group-directories-first'
  alias lt='eza --tree --level=2 --icons=auto --group-directories-first'
else
  alias ls='ls --color=auto'
  alias ll='ls -lah --color=auto'
  alias la='ls -A --color=auto'
fi

# -----------------------------
# Git
# -----------------------------

if command -v delta >/dev/null 2>&1; then
  export GIT_PAGER='delta'
fi


# -----------------------------
# Starship
# -----------------------------

if command -v starship >/dev/null 2>&1; then
  eval "$(starship init zsh)"
fi


# -----------------------------
# Atuin
# -----------------------------

if command -v atuin >/dev/null 2>&1; then
  eval "$(atuin init zsh)"
fi


# -----------------------------
# Zoxide
# -----------------------------

if command -v zoxide >/dev/null 2>&1; then
  eval "$(zoxide init zsh)"
fi

