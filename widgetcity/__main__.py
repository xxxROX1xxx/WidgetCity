import sys

from widgetcity.updates import INSTALL_ARG, run_installer

if getattr(sys, "frozen", False) and sys.argv[1:2] == [INSTALL_ARG]:
    raise SystemExit(run_installer(sys.argv[2:]))

from widgetcity.app import main

raise SystemExit(main())
