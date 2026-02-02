SchoolPoints - Cashier PC scripts

Folder purpose:
- Run and test Cashier Station directly from the network project folder.
- Avoid rebuilding EXE for every small fix.

1) Install once:
   01_install_deps_from_network.bat

2) Run cashier:
   02_run_cashier_from_network.bat

3) Test customer display (VeriFone):
   03_test_display_from_network.bat

4) Test printer:
   Open cashier -> Settings -> choose printer -> click Test Print.

Notes:
- Python must be installed and added to PATH.
- Dependencies are installed into a local venv at:
  %LOCALAPPDATA%\SchoolPoints\venv
- Project files are loaded from:
  \\Yankl-pc\c\מיצד\SchoolPoints
