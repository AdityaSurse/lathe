# VHS Tape Configuration for Lathe Agent Terminal Demo
# Record with: vhs demo.tape

Output assets/demo.gif

Set Shell "zsh"
Set FontSize 14
Set Width 1100
Set Height 620
Set LineHeight 1.2
Set Theme "Catppuccin Mocha"
Set WindowBar "Colorful"
Set WindowBarSize 36
Set Margin 20
Set MarginFill "#181825"
Set BorderRadius 10
Set Padding 10
Set TypingSpeed 50ms

# Setup virtual environment in background
Hide
Type "source .venv/bin/activate && clear"
Enter
Sleep 500ms
Show

# 1. Run lathe doctor to inspect runtime and models
Type "lathe doctor"
Sleep 500ms
Enter
Sleep 3000ms

# 2. Inspect Lathe command-line options
Type "lathe --help"
Sleep 500ms
Enter
Sleep 3000ms

# 3. Launch interactive prompt and run a command
Type "lathe"
Sleep 500ms
Enter
Sleep 2500ms

Type "/mode"
Sleep 300ms
Enter
Sleep 1500ms

Type "/tokens"
Sleep 300ms
Enter
Sleep 2000ms

Type "/exit"
Sleep 300ms
Enter
Sleep 1000ms
