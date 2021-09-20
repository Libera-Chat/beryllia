from enum      import Enum

from ircstates import casefold

class SearchType(Enum):
    NICK = 1
    USER = 2
    REAL = 3
    HOST = 4

class SearchNormaliser(object):
    def normalise(self,
            input: str,
            type:  SearchType
            ) -> str:
        return input

class RFC1459SearchNormaliser(SearchNormaliser):
    def normalise(self,
            input: str,
            type:  SearchType
            ) -> str:

        if type in {SearchType.NICK, SearchType.USER}:
            return casefold("rfc1459", input)
        else:
            return input.lower()
