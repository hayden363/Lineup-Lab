# Makes `tests` a package so `python -m unittest discover -s tests -t .` works on
# Python 3.9, which refuses to discover from a non-importable start directory.
