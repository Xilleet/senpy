import sys
import traceback

try:
    from senpy.cli.main import main
    sys.exit(main())
except Exception as e:
    sys.stderr.write(f"SENPY FATAL ERROR: {e}\n")
    sys.stderr.write(traceback.format_exc())
    sys.stderr.flush()
    sys.exit(1)
