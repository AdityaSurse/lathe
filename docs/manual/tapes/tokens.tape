Set Shell "zsh"
Set FontSize 15
Set Width 1050
Set Height 520
Set BorderRadius 10
Set Theme "Catppuccin Mocha"

Hide
Type "source .venv/bin/activate && export PYTHONPATH=src && clear" Enter
Sleep 1s
Show

Type "python scripts/demo_screens.py tokens" Enter
Sleep 2s
Screenshot "assets/manual/images/tokens.png"
Sleep 500ms
