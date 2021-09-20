import re, traceback
from datetime  import timedelta
from typing    import List, Optional, Tuple

from ircrobots import Server
from irctokens import build

from ircchallenge       import Challenge
from ircrobots.matching import ANY, Folded, Response, SELF
from ircstates.numerics import *

SECONDS_MINUTES = 60
SECONDS_HOURS   = SECONDS_MINUTES*60
SECONDS_DAYS    = SECONDS_HOURS*24
SECONDS_WEEKS   = SECONDS_DAYS*7
TIME_UNITS = list(zip(
    "wdhms",
    [SECONDS_WEEKS, SECONDS_DAYS, SECONDS_HOURS, SECONDS_MINUTES, 1]
))

def pretty_delta(
        delta:     timedelta,
        max_units: int=2
        ) -> str:

    denominator = int(delta.total_seconds())
    outs: List[str] = []
    for unit, div in TIME_UNITS:
        numerator, denominator = divmod(denominator, div)
        if numerator > 0:
            outs.append(f"{numerator}{unit}")
            if len(outs) == max_units:
                break

    return "".join(outs) or "0s"

async def oper_up(
        server:    Server,
        oper_name: str,
        oper_file: str,
        oper_pass: str):

    try:
        challenge = Challenge(keyfile=oper_file, password=oper_pass)
    except Exception:
        traceback.print_exc()
    else:
        await server.send(build("CHALLENGE", [oper_name]))
        challenge_text = Response(RPL_RSACHALLENGE2,      [SELF, ANY])
        challenge_stop = Response(RPL_ENDOFRSACHALLENGE2, [SELF])
        #:lithium.libera.chat 740 sandcat :foobarbazmeow
        #:lithium.libera.chat 741 sandcat :End of CHALLENGE

        while True:
            challenge_line = await server.wait_for({
                challenge_text, challenge_stop
            })
            if challenge_line.command == RPL_RSACHALLENGE2:
                challenge.push(challenge_line.params[1])
            else:
                retort = challenge.finalise()
                await server.send(build("CHALLENGE", [f"+{retort}"]))
                break
