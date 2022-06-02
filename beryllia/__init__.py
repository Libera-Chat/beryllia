from dataclasses import dataclass
from datetime import datetime, timedelta
from json import loads as json_loads
from re import compile as re_compile
from typing import Dict, List, Optional, Sequence, Tuple

from irctokens import build, hostmask as hostmask_parse, Hostmask, Line
from ircrobots import Bot as BaseBot
from ircrobots import Server as BaseServer

from ircstates.numerics import RPL_ENDOFMOTD, ERR_NOMOTD, RPL_WELCOME, RPL_YOUREOPER
from ircrobots.ircv3 import Capability

from .config import Config
from .database import Database
from .database.common import NickUserHost
from .database.kline import DBKLine
from .normalise import RFC1459SearchNormaliser

from .util import oper_up, pretty_delta, get_statsp, get_klines
from .util import try_parse_cidr, try_parse_ip, try_parse_ts
from .util import looks_like_glob, colourise

from .parse.nickserv import NickServParser
from .parse.snote import SnoteParser

RE_DATE = re_compile(r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$")

CAP_OPER = Capability(None, "solanum.chat/oper")
MASK_MAX = 3


@dataclass
class Caller:
    nick: str
    source: str
    oper: str


PREFERENCES: Dict[str, type] = {"statsp": bool, "knag": bool}


class Server(BaseServer):
    database: Database

    _nickserv: NickServParser
    _snote: SnoteParser

    def __init__(self, bot: BaseBot, name: str, config: Config):

        super().__init__(bot, name)
        self.desired_caps.add(CAP_OPER)

        self._config = config

        self._database_init: bool = False

    def set_throttle(self, rate: int, time: float):
        # turn off throttling
        pass

    async def minutely(self, now: datetime):
        # this might hit before we've made our database after RPL_ISUPPORT
        if not self._database_init:
            return
        async with self.read_lock:
            for oper, mask in await get_statsp(self):
                pref = await self.database.preference.get(oper, "statsp")
                if pref == False:
                    # explicitly `== False` because it could also be None
                    continue
                await self.database.statsp.add(oper, mask, now)

    async def _compare_klines(self):
        klines_db = await self.database.kline.list_active()
        klines_irc = await get_klines(self)

        # None if we didn't have permission to do it
        if klines_irc is None:
            return
        for kline_gone in set(klines_db) - klines_irc:
            kline_id = klines_db[kline_gone]
            await self.database.kline_remove.add(kline_id, None, None)
        # TODO: add new k-lines to database?

    async def _log(self, text: str):
        if self._config.log is not None:
            await self.send(build("PRIVMSG", [self._config.log, text]))

    async def _knag(self, oper: str, nick: str, kline_id: int, kline: DBKLine) -> None:
        pref = await self.database.preference.get(oper, "knag")
        if not pref == True:  # == True because it could be None
            return

        out = (
            f"k-line \2#{kline_id}\2 ({kline.mask}) set without a tag;"
            f" '/msg {self.nickname} ktag {kline_id} taghere' to tag it"
        )
        await self.send(build("NOTICE", [nick, out]))

    async def _kline_new(self, kline_id: int) -> None:
        kline = await self.database.kline.get(kline_id)

        if not await self.database.kline_tag.find_tags(kline_id):
            nickname = hostmask_parse(kline.source).nickname
            await self._knag(kline.oper, nickname, kline_id, kline)

        await self._log(
            f"KLINE:NEW: \2{kline_id}\2"
            f" by {colourise(kline.oper)}:"
            f" {kline.mask} {kline.reason}"
        )

    async def line_read(self, line: Line):
        if line.command == RPL_WELCOME:
            oper_name, oper_file, oper_pass = self._config.oper
            await oper_up(self, oper_name, oper_file, oper_pass)

        elif line.command in {RPL_ENDOFMOTD, ERR_NOMOTD}:
            # we should now know our casemap, so connect database.
            # we need the casemap for this to normalise things for searching
            self.database = database = await Database.connect(
                self._config.db_user,
                self._config.db_pass,
                self._config.db_host,
                self._config.db_name,
                RFC1459SearchNormaliser(),
            )
            self._database_init = True

            self._nickserv = NickServParser(database)
            self._snote = SnoteParser(database, self._config.rejects, self._kline_new)

        elif line.command == RPL_YOUREOPER:
            # B connections rejected due to k-line
            # F far cliconn
            # c near cliconn
            # k server kills
            # n nick changes
            # s oper kills, klines
            await self.send(build("MODE", [self.nickname, "-s+s", "+BFckns"]))
            await self._compare_klines()

        elif (
            line.command == "NOTICE"
            and line.params[0] == "*"
            and line.source is not None
            and not "!" in line.source
            and self.registered
        ):

            await self._snote.handle(line)

        elif (
            line.command == "PRIVMSG"
            and line.source is not None
            and not self.is_me(line.hostmask.nickname)
        ):

            await self._on_message(line)

    async def _on_message(self, line: Line) -> None:
        if line.hostmask.nickname == "NickServ":
            await self._nickserv.handle(line)
            return

        first, _, rest = line.params[1].partition(" ")
        if self.is_me(line.params[0]):
            # private message
            await self.cmd(
                line.hostmask, line.hostmask.nickname, first.lower(), rest, line.tags
            )
            return

        elif rest and first in {f"{self.nickname}{c}" for c in [":", ",", ""]}:
            # highlight in channel
            command, _, args = rest.partition(" ")
            await self.cmd(
                line.hostmask, line.params[0], command.lower(), args, line.tags
            )
            return

    async def cmd(
        self,
        who: Hostmask,
        target: str,
        command: str,
        args: str,
        tags: Optional[Dict[str, str]],
    ):

        if tags and (oper := tags.get("solanum.chat/oper", "")):
            caller = Caller(who.nickname, str(who), oper)
            attrib = f"cmd_{command}"
            if hasattr(self, attrib):
                outs = await getattr(self, attrib)(caller, args)
                for out in outs:
                    await self.send(build("NOTICE", [target, out]))

    async def cmd_help(self, caller: Caller, args: str):
        me = self.nickname
        command = args.lstrip().split(" ", 1)[0]
        if not command:
            return ["available commands: kcheck", f"usage: /msg {me} help <command>"]
        elif command == "kcheck":
            return [
                "search for bans that affected a nick/host/ip",
                f"usage: /msg {me} check <nick|host|ip> <query>",
            ]
        else:
            return ["unknown command"]

    async def _ktag(self, kline_id: int, tag: str, caller: Caller):

        if await self.database.kline_tag.exists(kline_id, tag):
            return [f"k-line {kline_id} is already tagged as '{tag}'"]

        await self.database.kline_tag.add(kline_id, tag, caller.source, caller.oper)
        kline = await self.database.kline.get(kline_id)
        kts = pretty_delta(datetime.utcnow() - kline.ts)
        return [f"tagged {kts} old k-line" f" (#{kline_id} \2{kline.mask}\2) as {tag}"]

    async def cmd_ktag(self, caller: Caller, sargs: str):
        args = sargs.split(None, 2)
        if len(args) < 2:
            return ["please provide a k-line ID and a tag"]
        elif not args[0].isdigit():
            return [f"'{args[0]}' doesn't look like a k-line ID"]
        elif not await self.database.kline.exists(kline_id := int(args[0])):
            return [f"k-line {kline_id} not found"]

        return await self._ktag(kline_id, args[1], caller)

    async def cmd_unktag(self, caller: Caller, sargs: str):
        args = sargs.split(None, 2)
        if len(args) < 2:
            return ["please provide a k-line ID and a tag"]
        elif not args[0].isdigit():
            return [f"'{args[0]}' doesn't look like a k-line ID"]
        elif not await self.database.kline.exists(kline_id := int(args[0])):
            return [f"k-line {kline_id} not found"]

        tag = args[1]
        if not await self.database.kline_tag.exists(kline_id, tag):
            return [f"k-line {kline_id} not tagged as '{tag}'"]

        await self.database.kline_tag.remove(kline_id, tag)
        return [f"removed tag '{tag}' from k-line {kline_id}"]

    async def cmd_ktaglast(self, caller: Caller, sargs: str):
        args = sargs.split(None, 2)
        if len(args) < 2:
            return ["please provide a k-line count and tag"]
        elif not args[0].isdigit():
            return [f"'{args[0]}' isn't a number"]

        kline_ids = await self.database.kline.find_last_by_oper(
            caller.oper, int(args[0])
        )
        outs: List[str] = []
        for kline_id in kline_ids:
            outs += await self._ktag(kline_id, args[1], caller)
        if not outs:
            outs = ["found no recent k-lines from you"]
        return outs

    async def cmd_kcheck(self, caller: Caller, sargs: str):
        args = sargs.split(None, 2)
        if len(args) < 2:
            return ["please provide a type and query"]

        type, queryv, *_ = args
        query = queryv.split()[0]
        type = type.lower()
        db = self.database
        now = datetime.utcnow()

        limit = 3
        if args and (limit_s := args[0]).isdigit():
            limit = int(limit_s)

        klines_: List[Tuple[int, datetime]] = []
        if type == "nick":
            klines_ += await db.kline_kill.find_by_nick(query)
            klines_ += await db.kline_reject.find_by_nick(query)
        elif type == "host":
            klines_ += await db.kline_kill.find_by_host(query)
            klines_ += await db.kline_reject.find_by_host(query)
        elif type == "mask":
            klines_ += await db.kline.find_by_mask_glob(query)
        elif type == "ts":
            if (dt := try_parse_ts(queryv)) is None:
                return [f"'{queryv}' does not look like a timestamp"]
            klines_ += await db.kline.find_by_ts(dt)
        elif type == "tag":
            klines_ += await db.kline_tag.find_klines(query)
        elif type == "id":
            if not query.isdigit() or not await db.kline.exists(query_id := int(query)):
                return [f"unknown k-line id {query}"]
            # kinda annoying that we get the k-line here just to pull
            # out ts + id, then we use that id later to get the same
            # k-line again later.
            kline = await db.kline.get(query_id)
            klines_.append((query_id, kline.ts))
        elif type == "ip":
            if (ip := try_parse_ip(query)) is not None:
                klines_ += await db.kline_kill.find_by_ip(ip)
                klines_ += await db.kline_reject.find_by_ip(ip)
            elif (cidr := try_parse_cidr(query)) is not None:
                klines_ += await db.kline_kill.find_by_cidr(cidr)
                klines_ += await db.kline_reject.find_by_cidr(cidr)
            elif looks_like_glob(query):
                klines_ += await db.kline_kill.find_by_ip_glob(query)
                klines_ += await db.kline_reject.find_by_ip_glob(query)
            else:
                return [f"'{query}' does not look like an IP address"]
        else:
            return [f"unknown query type '{type}'"]

        # sort by timestamp descending
        klines = sorted(set(klines_), key=lambda k: k[1], reverse=True)
        # apply output limit
        klines = klines[:limit]

        outs: List[str] = []
        for kline_id, _ in klines:
            kline = await db.kline.get(kline_id)
            remove = await db.kline_remove.get(kline_id)

            kts_human = pretty_delta(now - kline.ts)
            if remove is not None:
                remover = remove.oper or "unknown"
                remove_s = f"\x0303removed\x03 by \x02{remover}\x02"
            elif kline.expire < now:
                ts_since = pretty_delta(now - kline.expire)
                remove_s = f"\x0303expired {ts_since} ago\x03"
            else:
                ts_left = pretty_delta(kline.expire - now)
                remove_s = f"\x0304{ts_left} remaining\x03"

            kills = await db.kline_kill.find_by_kline(kline_id)
            rejects = await db.kline_reject.find_by_kline(kline_id)
            affected: Sequence[NickUserHost] = list(kills) + list(rejects)

            outs.append(
                f"K-Line \x02#{kline_id}\x02:"
                f" {kline.mask}"
                f" \x02{kts_human} ago\x02"
                f" by \x02{kline.oper}\x02"
                f" for {kline.duration//60} mins"
                f" ({remove_s})"
                f" {kline.reason}"
            )
            masks = sorted(set(nuh.nuh() for nuh in affected))
            outs.append("  affected: " + ", ".join(masks[:MASK_MAX]))
            if len(masks) > MASK_MAX:
                outs[-1] += f" (and {len(masks)-MASK_MAX} more)"

        return outs or ["no results"]

    async def cmd_cliconn(self, caller: Caller, sargs: str):
        args = sargs.split(None, 2)
        if len(args) < 2:
            return ["please provide a type and query"]

        type, query, *_ = args
        type = type.lower()
        db = self.database
        now = datetime.utcnow()

        cliconns_: List[Tuple[int, datetime]] = []
        if type == "nick":
            cliconns_ += await db.cliconn.find_by_nick(query)
            cliconns_ += await db.nick_change.find_cliconn(query)
        elif type == "user":
            cliconns_ += await db.cliconn.find_by_user(query)
        elif type == "host":
            cliconns_ += await db.cliconn.find_by_host(query)
        elif type == "ip":
            if (ip := try_parse_ip(query)) is not None:
                cliconns_ += await db.cliconn.find_by_ip(ip)
            elif (cidr := try_parse_cidr(query)) is not None:
                cliconns_ += await db.cliconn.find_by_cidr(cidr)
            elif looks_like_glob(query):
                cliconns_ += await db.cliconn.find_by_ip_glob(query)
            else:
                return [f"'{query}' does not look like an IP address"]
        else:
            return [f"unknown query type '{type}'"]

        # cut out duplicates
        # the database code does this already, but we might compile from
        # multiple database calls
        cliconns = sorted(set(cliconns_), key=lambda c: c[1], reverse=True)
        # cut it to 3 results. database code also does this, but see above
        cliconns = cliconns[:3]

        outs: List[str] = []
        for cliconn_id, _ in cliconns:
            cliconn = await db.cliconn.get(cliconn_id)
            cts_human = pretty_delta(now - cliconn.ts)
            nick_chg = await db.nick_change.get(cliconn_id)

            outs.append(
                f"\x02{cts_human}\x02 ago -" f" {cliconn.nuh()} [{cliconn.realname}]"
            )
            if nick_chg:
                nick_chg_s = ", ".join(nick_chg)
                outs.append(f"  nicks: {nick_chg_s}")

        return outs or ["no results"]

    async def cmd_statsp(self, caller: Caller, args: str):
        match = RE_DATE.search(args.strip() or "1970-01-01")
        if match is None:
            return ["that's not a date"]

        since_ts = datetime.strptime(match.group(0), "%Y-%m-%d")
        statsp_d = await self.database.statsp.count_since(since_ts)
        col_size = max([len(str(m)) for m in statsp_d.values()])

        outs: List[str] = []
        for oper, minutes in statsp_d.items():
            mins_str = str(minutes).rjust(col_size)
            outs.append(f"{mins_str} mins - {oper}")

        total_min = sum(statsp_d.values())
        total_str = pretty_delta(timedelta(minutes=total_min), long=True)
        outs.append(f"total: {total_str}")

        return outs

    async def cmd_pref(self, caller: Caller, sargs: str):
        args = sargs.split(None, 1)
        db = self.database
        if len(args) == 0:
            keys = ", ".join(sorted(PREFERENCES.keys()))
            return [f"available preferences: {keys}"]
        elif not (key := args[0].lower()) in PREFERENCES:
            return [f"unknown preference '{key}'"]
        elif len(args) == 1:
            value = await db.preference.get(caller.oper, key := args[0].lower())
            return [f"{key} == {value}"]
        elif not type(value := json_loads(args[1])) == PREFERENCES[key]:
            return [f"invalid value type '{type(value)}' for key {key}"]

        await db.preference.set(caller.oper, key, value)
        return [f"set {key} to {value}"]

    def line_preread(self, line: Line):
        print(f"< {line.format()}")

    def line_presend(self, line: Line):
        print(f"> {line.format()}")


class Bot(BaseBot):
    def __init__(self, config: Config):
        super().__init__()
        self._config = config

    def create_server(self, name: str):
        return Server(self, name, self._config)
