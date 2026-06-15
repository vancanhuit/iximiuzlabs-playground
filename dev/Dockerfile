# syntax=docker/dockerfile:1
FROM ghcr.io/vancanhuit/debian-rootfs:trixie-base

ARG LAB_USER=laborant

# --- Install zsh and make it the lab user's default shell (needs root) ---
USER root
ENV DEBIAN_FRONTEND=noninteractive
RUN <<EOF
set -eu
apt-get update
apt-get install -y zsh build-essential
chsh -s "$(command -v zsh)" "$LAB_USER"
apt-get clean -y
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
EOF

# --- Everything below runs as the lab user ---
USER $LAB_USER
ENV HOME=/home/$LAB_USER
WORKDIR $HOME

# Install mise (https://mise.jdx.dev/getting-started.html)
RUN curl https://mise.run | sh
ENV PATH="$HOME/.local/bin:$PATH"

# Install development tools via mise
RUN --mount=type=secret,id=github_token,env=GITHUB_TOKEN \
  mise use -g \
  starship \
  ripgrep \
  fd \
  lazygit \
  neovim \
  ast-grep \
  tree-sitter \
  fzf \
  bat \
  shellcheck \
  shfmt \
  python@3.14.6 \
  uv \
  ruff \
  delta \
  node@lts \
  atuin \
  eza

# Neovim language providers: pynvim via uv, neovim package via npm
RUN <<EOF 
#!/usr/bin/env zsh
set -e
eval "$(mise activate zsh)"
uv tool install pynvim
npm install -g neovim
EOF

# Shell and prompt configuration
COPY --chown=$LAB_USER:$LAB_USER .zshrc $HOME/.zshrc
COPY --chown=$LAB_USER:$LAB_USER starship.toml $HOME/.config/starship.toml

# Git configuration
RUN <<EOF
set -eu
git config --global init.defaultBranch main
git config --global core.editor nvim
git config --global core.pager delta
git config --global interactive.diffFilter "delta --color-only"
git config --global delta.navigate true
git config --global delta.line-numbers true
git config --global delta.side-by-side false
git config --global diff.colorMoved default
git config --global merge.conflictstyle zdiff3
git config --global pull.rebase true
git config --global push.autoSetupRemote true
git config --global fetch.prune true
git config --global branch.sort -committerdate
git config --global column.ui auto
git config --global rerere.enabled true
EOF

# LazyVim starter configuration
RUN git clone --depth 1 https://github.com/LazyVim/starter $HOME/.config/nvim \
  && rm -rf $HOME/.config/nvim/.git
