import os
import pwd
import grp
from pathlib import Path


def _drop_privileges(data_dir: Path) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        return
    user = pwd.getpwnam("nobody")
    group = grp.getgrnam("nogroup")
    os.chown(data_dir, user.pw_uid, group.gr_gid)
    for entry in os.scandir(data_dir):
        os.chown(
            entry.path,
            user.pw_uid,
            group.gr_gid,
            follow_symlinks=False,
        )
    os.setgroups([])
    os.setgid(group.gr_gid)
    os.setuid(user.pw_uid)


def main() -> None:
    data_dir = Path(os.environ.get("DATA_DIR", "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    _drop_privileges(data_dir)

    from apps.api.main import main as serve

    serve()


if __name__ == "__main__":
    main()
