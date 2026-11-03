#!/usr/bin/env python3
"""Fail before expensive candidate work if tools or resources are absent."""
import argparse
from pathlib import Path
from lib.xfce_launch import preflight, check_kvm

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind',choices=['tools','build','consumer','vm','kvm'])
    parser.add_argument('--path',type=Path,default=Path('.'))
    args=parser.parse_args()
    try:
        if args.kind=='kvm':
            check_kvm()
        else:
            preflight(args.path,args.kind)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except OSError:
        raise SystemExit('candidate prerequisite inaccessible; KVM checks never alter permissions or fall back to TCG') from None
    except KeyError:
        raise SystemExit('candidate prerequisite check failed; needs yq, 12 GiB available RAM, 4 CPUs and the documented free disk budget') from None
