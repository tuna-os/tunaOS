# ~/.zshrc - User zsh configuration
# This file is sourced for interactive shells

# Source global definitions
if [ -f /etc/zshrc ]; then
    . /etc/zshrc
fi

# User specific environment
if ! [[ "$PATH" =~ "$HOME/.local/bin:$HOME/bin:" ]]; then
    PATH="$HOME/.local/bin:$HOME/bin:$PATH"
fi
export PATH

# History configuration
HISTFILE=~/.zsh_history
HISTSIZE=10000
SAVEHIST=10000

# Enable command completion
autoload -Uz compinit
compinit

# Enable colors
autoload -U colors && colors

