from collections import deque
from dataclasses import dataclass
from typing      import Deque, Union

from asyncpg     import Connection, Pool
from ..normalise import SearchNormaliser, SearchType
from ..util      import CompositeString, CompositeStringText

class NickUserHost:
    # nick user host
    def nuh(self) -> str:
        raise NotImplementedError()

@dataclass
class Table(object):
    pool:       Pool
    normaliser: SearchNormaliser

    def to_search(self,
            input_: Union[str, CompositeString],
            type:   SearchType
            ) -> CompositeString:

        if isinstance(input_, str):
            input = CompositeString([CompositeStringText(input_)])
        else:
            input = input_

        return self.normaliser.normalise(input, type)
