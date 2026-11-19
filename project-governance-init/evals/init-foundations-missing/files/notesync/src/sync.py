import shutil
import sys


def sync(src: str, dst: str) -> None:
    shutil.copytree(src, dst, dirs_exist_ok=True)


if __name__ == "__main__":
    sync(sys.argv[1], sys.argv[2])
