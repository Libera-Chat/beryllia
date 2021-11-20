from enum      import Enum
from typing    import Deque

from ircstates import casefold

from .util     import (CompositeString, CompositeStringType,
    CompositeStringText)

class SearchType(Enum):
    NICK = 1
    USER = 2
    REAL = 3
    HOST = 4

class SearchNormaliser(object):
    def normalise(self,
            input: CompositeString,
            type:  SearchType
            ) -> CompositeString:
        return input

class RFC1459SearchNormaliser(SearchNormaliser):
    def normalise(self,
            input: CompositeString,
            type:  SearchType
            ) -> CompositeString:

        out = CompositeString()
        for part in input:
            if part.type == CompositeStringType.TEXT:
                if type in {SearchType.NICK, SearchType.USER}:
                    text = casefold("rfc1459", part.text)
                else:
                    text = part.text.lower()
                out.append(CompositeStringText(text))
            else:
                out.append(part)
        return out
