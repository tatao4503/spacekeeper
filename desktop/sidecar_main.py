"""Self-contained entry point for the bundled Spacekeeper dashboard server.

기본은 대시보드 서버를 실행하고, launchd 예약 에이전트가 ``--scheduled-run``
인자로 호출하면 예약 정리를 수행한다.
"""

import sys

if __name__ == "__main__":
    if "--scheduled-run" in sys.argv[1:]:
        from spacekeeper.scheduler import run_scheduled

        run_scheduled()
    else:
        from spacekeeper.server import serve

        serve()
