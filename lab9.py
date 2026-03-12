import os
import sys
from network import Node, run_registrar


def main():
    role = os.environ.get("ROLE")
    if len(sys.argv) > 1:
        role = sys.argv[1]

    if role == "registrar":
        port = int(os.environ.get("LISTEN_PORT", "58333"))
        run_registrar(port)
    else:
        Node().run()


if __name__ == "__main__":
    main()
