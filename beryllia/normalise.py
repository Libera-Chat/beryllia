from enum import Enum
from typing import Set

from ircstates import casefold, CaseMap

from .util import CompositeString, CompositeStringType, CompositeStringText


class SearchType(Enum):
    NICK = 1
    USER = 2
    REAL = 3
    HOST = 4
    TAG = 5
    MASK = 6
    EMAIL = 7


class SearchNormaliser(object):
    def normalise(self, input: CompositeString, type: SearchType) -> CompositeString:
        return input


class RFC1459SearchNormaliser(SearchNormaliser):
    def normalise(self, input: CompositeString, type: SearchType) -> CompositeString:

        out = CompositeString()
        seen_chars: Set[int] = set()
        for part in input:
            if part.type == CompositeStringType.TEXT:
                if type in {SearchType.NICK, SearchType.USER}:
                    text = casefold(CaseMap.RFC1459, part.text)
                elif type == SearchType.MASK:
                    if ord("@") in seen_chars:
                        text = part.text.lower()
                    elif not "@" in part.text:
                        text = casefold(CaseMap.RFC1459, part.text)
                    else:
                        user, _, host = part.text.partition("@")
                        text = casefold(CaseMap.RFC1459, user)
                        text += "@"
                        text += casefold(CaseMap.RFC1459, host)
                else:
                    text = part.text.lower()

                out.append(CompositeStringText(text))
                seen_chars.update(ord(c) for c in part.text)
            else:
                out.append(part)
        return out
