from dataclasses import dataclass

from asyncpg     import Connection
from ..normalise import SearchNormaliser, SearchType

@dataclass
class Table(object):
    connection: Connection
    normaliser: SearchNormaliser

    def to_search(self,
            input: str,
            type:  SearchType
            ) -> str:

        return self.normaliser.normalise(input, type)
