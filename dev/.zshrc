# ~/.zshrc

export GPG_TTY=$(tty)
export LANG=en_US.UTF-8
export LC_ALL=C.UTF-8

# -----------------------------
# PATH
# -----------------------------
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
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

# User completion functions (mise, etc.) must be on fpath before compinit.
fpath=("$HOME/.local/share/zsh/site-functions" $fpath)

# Regenerate tool completions onto fpath *before* compinit so they load this
# session. Track changes so we can force a dump rebuild when one is updated.
_comp_changed=0
if command -v mise >/dev/null 2>&1; then
  _mise_comp="$HOME/.local/share/zsh/site-functions/_mise"
  mkdir -p "${_mise_comp:h}"
  if [[ ! -f "$_mise_comp" || $commands[mise] -nt "$_mise_comp" ]]; then
    mise completion zsh > "$_mise_comp" 2>/dev/null && _comp_changed=1
  fi
  unset _mise_comp
fi

autoload -Uz compinit
# Rebuild the dump when a completion changed, once a day, or if it's missing;
# otherwise load from cache for fast startup.
_zcompdump="$HOME/.zcompdump"
if (( _comp_changed )) || [[ -n "$_zcompdump"(#qNmh+24) ]] || [[ ! -f "$_zcompdump" ]]; then
  compinit -d "$_zcompdump"
else
  compinit -C -d "$_zcompdump"
fi
unset _zcompdump _comp_changed

# Complete command options after arguments/subcommands, e.g.:
# apt purge --<TAB>
zstyle ':completion:*' complete-options true

# Show descriptions/groups in completion menu.
zstyle ':completion:*' verbose true
zstyle ':completion:*:descriptions' format '%F{yellow}-- %d --%f'
zstyle ':completion:*:messages' format '%F{purple}-- %d --%f'
zstyle ':completion:*:warnings' format '%F{red}-- no matches --%f'
zstyle ':completion:*:corrections' format '%F{green}-- %d (errors: %e) --%f'
zstyle ':completion:*' group-name ''

# Pick up newly installed binaries (e.g. via mise) without a manual rehash.
zstyle ':completion:*' rehash true

# Cache slow completions (apt, etc.).
zstyle ':completion:*' use-cache on
zstyle ':completion:*' cache-path "$HOME/.zcompcache"

# Interactive menu + smart matching.
zstyle ':completion:*' menu select
# Case-insensitive, then partial-word, then substring matching.
zstyle ':completion:*' matcher-list \
  'm:{a-zA-Z}={A-Za-z}' \
  'r:|[._-]=* r:|=*' \
  'l:|=* r:|=*'
zstyle ':completion:*' completer _complete _match _extensions _approximate _ignored
zstyle ':completion:*:approximate:*' max-errors 'reply=( $((($#PREFIX+$#SUFFIX)/3)) )'
zstyle ':completion:*' squeeze-slashes true
zstyle ':completion:*' special-dirs true

# Better process completion for kill/killall.
zstyle ':completion:*:*:kill:*:processes' list-colors '=(#b) #([0-9]#)*=0=01;31'
zstyle ':completion:*:*:*:*:processes' command 'ps -u $USER -o pid,user,comm -w -w'

# Use LS_COLORS for completion colors when available.
if [[ -n "$LS_COLORS" ]]; then
  zstyle ':completion:*' list-colors "${(s.:.)LS_COLORS}"
fi

# Navigate the completion menu with vim keys.
zmodload zsh/complist
bindkey -M menuselect 'h' vi-backward-char
bindkey -M menuselect 'j' vi-down-line-or-history
bindkey -M menuselect 'k' vi-up-line-or-history
bindkey -M menuselect 'l' vi-forward-char


# -----------------------------
# Colors
# -----------------------------

autoload -Uz colors && colors

# -----------------------------
# mise
# -----------------------------

if command -v mise >/dev/null 2>&1; then
  # Completion is regenerated in the Completion section (before compinit).
  eval "$(mise activate zsh)"
fi


# -----------------------------
# fzf
# -----------------------------

if command -v fzf >/dev/null 2>&1; then
  export FZF_DEFAULT_OPTS='--height 40% --layout=reverse --border'
  # Enable fzf key bindings (Ctrl-R, Ctrl-T, Alt-C) and tab completion.
  source <(fzf --zsh) 2>/dev/null
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
