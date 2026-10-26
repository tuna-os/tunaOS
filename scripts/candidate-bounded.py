#!/usr/bin/env python3
"""Clamp each candidate phase to the campaign's remaining shared deadline."""
import os
import sys
import time


def command(argv, deadline, now):
    cap=int(argv[0])
    remaining=int(deadline)-int(now)-5  # reserve timeout's TERM-to-KILL grace
    if cap<=0 or remaining<=0 or not argv[1:]:
        raise ValueError('candidate phase budget exhausted or invalid')
    return ['timeout','--signal=TERM','--kill-after=5s',str(min(cap,remaining)),*argv[1:]]


if __name__=='__main__':
    try:
        args=command(sys.argv[1:],os.environ['TUNAOS_XFCE_DEADLINE'],time.time())
    except (KeyError,ValueError):
        raise SystemExit('candidate shared phase budget unavailable or exhausted') from None
    os.execvp(args[0],args)
