from . import PyJEMService
import argparse
from pigeon.utils import setup_logging


def main():
    parser = argparse.ArgumentParser(prog="pyjem_service")
    parser.add_argument("--host", type=str, help="The message broker to connect to.")
    parser.add_argument("--port", type=int, help="The port to use for the connection.")
    parser.add_argument(
        "--username",
        type=str,
        help="The username to use when connecting to the STOMP server.",
    )
    parser.add_argument(
        "--password",
        type=str,
        help="The password to use when connecting to the STOMP server.",
    )

    args = parser.parse_args()

    setup_logging()

    pyjem_service = PyJEMService(
        host=args.host, port=args.port, username=args.username, password=args.password
    )
    pyjem_service.run()


if __name__ == "__main__":
    main()
