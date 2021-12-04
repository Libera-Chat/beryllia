import asyncio, ipaddress, re, time
from collections import OrderedDict
from datetime    import datetime, timedelta
from ipaddress   import IPv4Address, IPv6Address
from typing      import Dict, List, Optional, Set, Tuple, Union
from typing      import OrderedDict as TOrderedDict

from irctokens import build, Line
from ircrobots import Bot as BaseBot
from ircrobots import Server as BaseServer

from ircstates.numerics import *
from ircrobots.ircv3    import Capability
from ircrobots.matching import ANY, Folded, Response, SELF

from .config    import Config
from .database  import Database
from .normalise import RFC1459SearchNormaliser

from .util      import oper_up, pretty_delta, get_statsp, get_klines
from .util      import try_parse_cidr, try_parse_ip, try_parse_ts
from .util      import looks_like_glob

RE_CLICONN   = re.compile(r"^\*{3} Notice -- Client connecting: (?P<nick>\S+) \((?P<user>[^@]+)@(?P<host>\S+)\) \[(?P<ip>\S+)\] \S+ <(?P<account>\S+)> \[(?P<real>.*)\]$")
RE_CLIEXIT   = re.compile(r"^\*{3} Notice -- Client exiting: (?P<nick>\S+) \((?P<user>[^@]+)@(?P<host>\S+)\) .* \[(?P<ip>\S+)\]$")
RE_KLINEADD  = re.compile(r"^\*{3} Notice -- (?P<source>[^{]+)\{(?P<oper>[^}]+)\} added (?:temporary|global) (?P<duration>\d+) min\. K-Line for \[(?P<mask>\S+)\] \[(?P<reason>.*)\]$")
RE_KLINEDEL  = re.compile(r"^\*{3} Notice -- (?P<source>[^{]+)\{(?P<oper>[^}]+)\} has removed the (?:temporary|global) K-Line for: \[(?P<mask>\S+)\]$")
RE_KLINEEXIT = re.compile(r"^\*{3} Notice -- (?:KLINE active for|Disconnecting K-Lined user) (?P<nickname>\S+)\[[^]]+\] .(?P<mask>\S+).$")
RE_KLINEREJ  = re.compile(r"^\*{3} Notice -- Rejecting K-Lined user (?P<nick>\S+)\[(?P<user>[^]@]+)@(?P<host>[^]]+)\] .(?P<ip>\S+). .(?P<mask>\S+).$")
RE_NICKCHG   = re.compile(r"^\*{3} Notice -- Nick change: From (?P<old_nick>\S+) to (?P<new_nick>\S+) .(?P<userhost>\S+).$")
RE_DATE      = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$")

CAP_OPER = Capability(None, "solanum.chat/oper")
MASK_MAX = 3

class Server(BaseServer):
    database: Database

    def __init__(self,
            bot:    BaseBot,
            name:   str,
            config: Config):

        super().__init__(bot, name)
        self.desired_caps.add(CAP_OPER)

        self._config  = config

        self._database_init: bool = False
        self._wait_for_exit: Dict[str, str] = {}

        self._cliconns: Dict[str, int] = {}

    def set_throttle(self, rate: int, time: float):
        # turn off throttling
        pass

    async def minutely(self, now: datetime):
        # this might hit before we've made our database after RPL_ISUPPORT
        if self._database_init:
            async with self.read_lock:
                for oper, mask in await get_statsp(self):
                    await self.database.statsp.add(oper, mask, now)

    async def _compare_klines(self):
        klines_db  = await self.database.kline.list_active()
        klines_irc = await get_klines(self)

        # None if we didn't have permission to do it
        if klines_irc is not None:
            for kline_gone in set(klines_db) - klines_irc:
                kline_id = klines_db[kline_gone]
                await self.database.kline_remove.add(kline_id, None, None)
        # TODO: add new k-lines to database?

    async def line_read(self, line: Line):
        now = time.monotonic()

        if line.command == RPL_WELCOME:
            await self.send(build("MODE", [self.nickname, "+g"]))
            oper_name, oper_file, oper_pass = self._config.oper
            await oper_up(self, oper_name, oper_file, oper_pass)

        elif line.command in {RPL_ENDOFMOTD, ERR_NOMOTD}:
            # we should now know our casemap, so connect database.
            # we need the casemap for this to normalise things for searching
            self.database = await Database.connect(
                self._config.db_user,
                self._config.db_pass,
                self._config.db_host,
                self._config.db_name,
                RFC1459SearchNormaliser()
            )
            self._database_init = True

        elif line.command == RPL_YOUREOPER:
            # B connections rejected due to k-line
            # F far cliconn
            # c near cliconn
            # k server kills
            # n nick changes
            # s oper kills, klines
            await self.send(build("MODE", [self.nickname, "-s+s", "+BFckns"]))
            await self._compare_klines()

        elif (line.command == "NOTICE" and
                line.params[0] == "*" and
                line.source is not None and
                not "!" in line.source):

            # snote!

            message     = line.params[1]
            p_cliconn   = RE_CLICONN.search(message)
            p_cliexit   = RE_CLIEXIT.search(message)
            p_klineadd  = RE_KLINEADD.search(message)
            p_klinedel  = RE_KLINEDEL.search(message)
            p_klineexit = RE_KLINEEXIT.search(message)
            p_klinerej  = RE_KLINEREJ.search(message)
            p_nickchg   = RE_NICKCHG.search(message)

            if p_cliconn is not None:
                nickname = p_cliconn.group("nick")
                username = p_cliconn.group("user")
                realname = p_cliconn.group("real")
                hostname = p_cliconn.group("host")

                ip: Optional[Union[IPv4Address, IPv6Address]] = None
                if not (ip_str := p_cliconn.group("ip")) == "0":
                    ip = ipaddress.ip_address(ip_str)

                account: Optional[str] = None
                if not (account_ := p_cliconn.group("account")) == "*":
                    account = account_

                cliconn_id = await self.database.cliconn.add(
                    nickname,
                    username,
                    realname,
                    hostname,
                    account,
                    ip,
                    line.source
                )
                self._cliconns[nickname] = cliconn_id

            elif p_nickchg is not None:
                old_nick = p_nickchg.group("old_nick")
                new_nick = p_nickchg.group("new_nick")
                if old_nick in self._cliconns:
                    cliconn_id = self._cliconns.pop(old_nick)
                    self._cliconns[new_nick] = cliconn_id
                    await self.database.nick_change.add(cliconn_id, new_nick)

            elif p_cliexit is not None:
                nickname = p_cliexit.group("nick")
                username = p_cliexit.group("user")
                hostname = p_cliexit.group("host")

                ip: Optional[Union[IPv4Address, IPv6Address]] = None
                if not (ip_str := p_cliexit.group("ip")) == "0":
                    ip = ipaddress.ip_address(ip_str)

                if nickname in self._cliconns:
                    cliconn_id = self._cliconns.pop(nickname)
                    await self.database.cliexit.add(cliconn_id)

                if nickname in self._wait_for_exit:
                    mask     = self._wait_for_exit.pop(nickname)
                    kline_id = await self.database.kline.find_active(mask)
                    if kline_id is not None:
                        await self.database.kline_kill.add(
                            kline_id, nickname, username, hostname, ip
                        )

            elif p_klineadd is not None:
                source   = p_klineadd.group("source")
                oper     = p_klineadd.group("oper")
                mask     = p_klineadd.group("mask")
                duration = p_klineadd.group("duration")
                reason   = p_klineadd.group("reason")

                old_id = await self.database.kline.find_active(mask)
                id     = await self.database.kline.add(
                    source, oper, mask, int(duration)*60, reason
                )

                # if an existing k-line is being extended/updated, update
                # kills affected by the first k-line
                if old_id is not None:
                    db    = self.database
                    kills = await db.kline_kill.find_by_kline(old_id)
                    for kill in kills:
                        await db.kline_kill.set_kline(kill.id, id)

            elif p_klinedel is not None:
                source = p_klinedel.group("source")
                oper   = p_klinedel.group("oper")
                mask   = p_klinedel.group("mask")
                id     = await self.database.kline.find_active(mask)
                if id is not None:
                    await self.database.kline_remove.add(id, source, oper)

            elif p_klineexit is not None:
                nickname = p_klineexit.group("nickname")
                mask     = p_klineexit.group("mask")
                # we wait until cliexit because that snote has an IP in it
                self._wait_for_exit[nickname] = mask

            elif p_klinerej is not None:
                nickname = p_klinerej.group("nick")
                username = p_klinerej.group("user")
                hostname = p_klinerej.group("host")
                mask     = p_klinerej.group("mask")

                ip: Optional[Union[IPv4Address, IPv6Address]] = None
                if not (ip_str := p_klinerej.group("ip")) == "0":
                    ip = ipaddress.ip_address(ip_str)

                kline_id = await self.database.kline.find_active(mask)
                if kline_id is not None:
                    found = await self.database.kline_reject.find(
                        kline_id, nickname, username, hostname, ip
                    )
                    if found is None:
                        await self.database.kline_reject.add(
                            kline_id, nickname, username, hostname, ip
                        )

        elif (line.command == "PRIVMSG" and
                not self.is_me(line.hostmask.nickname)):

            me  = self.nickname
            who = line.hostmask.nickname

            first, _, rest = line.params[1].partition(" ")
            if self.is_me(line.params[0]):
                # private message
                await self.cmd(who, who, first.lower(), rest, line.tags)
            elif rest:
                if first in [me, f"{me}:", f"{me},"]:
                    # highlight in channel
                    command, _, args = rest.partition(" ")
                    await self.cmd(
                        who, line.params[0], command.lower(), args, line.tags
                    )

    async def cmd(self,
            who:     str,
            target:  str,
            command: str,
            args:    str,
            tags:    Optional[Dict[str, str]]
            ):

        if tags and "solanum.chat/oper" in tags:
            attrib  = f"cmd_{command}"
            if hasattr(self, attrib):
                outs = await getattr(self, attrib)(who, args)
                for out in outs:
                    await self.send(build("NOTICE", [target, out]))

    async def cmd_help(self, nick: str, args: str):
        me      = self.nickname
        command = args.lstrip().split(" ", 1)[0]
        if not command:
            return [
                "available commands: kcheck",
                f"usage: /msg {me} help <command>"
            ]
        elif command == "kcheck":
            return [
                "search for bans that affected a nick/host/ip",
                f"usage: /msg {me} check <nick|host|ip> <query>"
            ]
        else:
            return ["unknown command"]

    async def cmd_kcheck(self, nick: str, sargs: str):
        args = sargs.split(None, 1)
        if len(args) > 1:
            type, queryv = args
            query = queryv.split()[0]
            type  = type.lower()
            db    = self.database
            now   = datetime.utcnow()

            limit = 3
            if args and (limit_s := args[0]).isdigit():
                limit = int(limit_s)

            klines_: List[Tuple[int, datetime]] = []
            if   type == "nick":
                klines_ += await db.kline_kill.find_by_nick(query)
                klines_ += await db.kline_reject.find_by_nick(query)
            elif type == "host":
                klines_ += await db.kline_kill.find_by_host(query)
                klines_ += await db.kline_reject.find_by_host(query)
            elif type == "ts":
                if (dt := try_parse_ts(queryv)) is not None:
                    klines_ += await db.kline.find_by_ts(dt)
                else:
                    return [f"'{queryv}' does not look like a timestamp"]
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
                kline  = await db.kline.get(kline_id)
                remove = await db.kline_remove.get(kline_id)

                kts_human = pretty_delta(now-kline.ts)
                if remove is not None:
                    remover  = remove.oper or "unknown"
                    remove_s = f"\x0303removed\x03 by \x02{remover}\x02"
                elif kline.expire < now:
                    remove_s = "\x0303expired\x03"
                else:
                    ts_left  = pretty_delta(kline.expire-now)
                    remove_s = f"\x0304{ts_left} remaining\x03"

                kills   = await db.kline_kill.find_by_kline(kline_id)
                rejects = await db.kline_reject.find_by_kline(kline_id)
                affected: List[NickUserHost] = list(kills) + list(rejects)

                masks = sorted(set(nuh.nuh() for nuh in affected))
                outs.append("affected: " + ", ".join(masks[:MASK_MAX]))
                if len(masks) > MASK_MAX:
                    outs[-1] += f" (and {len(masks)-MASK_MAX} more)"

                outs.append(
                    "  \x02K-Line\x02:"
                    f" {kline.mask}"
                    f" \x02{kts_human} ago\x02"
                    f" by \x02{kline.oper}\x02"
                    f" for {kline.duration//60} mins"
                    f" ({remove_s})"
                    f" {kline.reason}"
                )

            return outs or ["no results"]
        else:
            return ["please provide a type and query"]

    async def cmd_cliconn(self, nick: str, sargs: str):
        args = sargs.split(None, 2)
        if len(args) > 1:
            type, query, *_ = args
            type = type.lower()
            db   = self.database
            now  = datetime.utcnow()

            cliconns_: List[Tuple[int, datetime]] = []
            if   type == "nick":
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
            cliconns = sorted(
                set(cliconns_), key=lambda c: c[1], reverse=True
            )
            # cut it to 3 results. database code also does this, but see above
            cliconns = cliconns[:3]

            outs: List[str] = []
            for cliconn_id, _ in cliconns:
                cliconn   = await self.database.cliconn.get(cliconn_id)
                cts_human = pretty_delta(now-cliconn.ts)
                outs.append(
                    f"\x02{cts_human}\x02 ago -"
                    f" {cliconn.nuh()} [{cliconn.realname}]"
                )
            return outs or ["no results"]
        else:
            return ["please provide a type and query"]

    async def cmd_statsp(self,
            nick: str,
            args: str):

        match = RE_DATE.search(args.strip() or "1970-01-01")
        if match is not None:
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
        else:
            return [f"that's not a date"]


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

