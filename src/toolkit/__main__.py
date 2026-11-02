"""Permite ejecutar ``python -m toolkit`` (equivalente al comando ``toolkit``)."""

from toolkit.bootstrap import main

if __name__ == "__main__":
    raise SystemExit(main())
