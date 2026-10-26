#!/usr/bin/env python3
"""Fail before expensive candidate work if tools or resources are absent."""
import argparse
from pathlib import Path
from lib.xfce_launch import preflight

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind',choices=['tools','build','consumer','vm'])
    parser.add_argument('--path',type=Path,default=Path('.'))
    args=parser.parse_args()
    try:
        preflight(args.path,args.kind)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except (OSError,KeyError):
        raise SystemExit('candidate prerequisite check failed; needs yq, 12 GiB available RAM, 4 CPUs and the documented free disk budget') from None
