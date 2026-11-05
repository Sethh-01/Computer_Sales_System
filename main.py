import os
from apps.api.main import main

os.environ.setdefault("HOST", "0.0.0.0")

if __name__ == "__main__":
    main()
