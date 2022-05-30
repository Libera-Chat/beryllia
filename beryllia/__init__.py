import asyncio, ipaddress, re, time
from collections import OrderedDict
from dataclasses import dataclass
from datetime    import datetime, timedelta
from ipaddress   import IPv4Address, IPv6Address
from json        import loads as json_loads
from typing      import Dict, List, Optional, Set, Tuple, Union
from typing      import OrderedDict as TOrderedDict

from irctokens import build, Hostmask, Line
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
from .util      import looks_like_glob, colourise, recursive_mx_resolve

RE_CLICONN   = re.compile(r"^\*{3} Notice -- Client connecting: (?P<nick>\S+) \((?P<user>[^@]+)@(?P<host>\S+)\) \[(?P<ip>\S+)\] \S+ <(?P<account>\S+)> \[(?P<real>.*)\]$")
RE_CLIEXIT   = re.compile(r"^\*{3} Notice -- Client exiting: (?P<nick>\S+) \((?P<user>[^@]+)@(?P<host>\S+)\) \[(?P<reason>.*)\] \[(?P<ip>\S+)\]$")
RE_KLINEADD  = re.compile(r"^\*{3} Notice -- (?P<source>[^{]+)\{(?P<oper>[^}]+)\} added (?:temporary|global) (?P<duration>\d+) min\. K-Line for \[(?P<mask>\S+)\] \[(?P<reason>.*)\]$")
RE_KLINEDEL  = re.compile(r"^\*{3} Notice -- (?P<source>[^{]+)\{(?P<oper>[^}]+)\} has removed the (?:temporary|global) K-Line for: \[(?P<mask>\S+)\]$")
RE_KLINEEXIT = re.compile(r"^\*{3} Notice -- (?:KLINE active for|Disconnecting K-Lined user) (?P<nickname>\S+)\[[^]]+\] .(?P<mask>\S+).$")
RE_KLINEREJ  = re.compile(r"^\*{3} Notice -- Rejecting K-Lined user (?P<nick>\S+)\[(?P<user>[^]@]+)@(?P<host>[^]]+)\] .(?P<ip>\S+). .(?P<mask>\S+).$")
RE_NICKCHG   = re.compile(r"^\*{3} Notice -- Nick change: From (?P<old_nick>\S+) to (?P<new_nick>\S+) .(?P<userhost>\S+).$")
RE_DATE      = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$")
RE_REGISTRAT = re.compile(r"^NickServ (?P<nickname>\S+) REGISTER: (?P<account>\S+) to (?P<email>\S+)$")

RE_KLINETAG  = re.compile(r"%(\S+)")

CAP_OPER = Capability(None, "solanum.chat/oper")
MASK_MAX = 3

@dataclass
class Caller:
    nick:   str
    source: str
    oper:   str

PREFERENCES: Dict[str, type] = {
    "statsp": bool,
    "knag": bool
}

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
                    pref = await self.database.preference.get(
                        oper, "statsp"
                    )
                    if pref is None or pref:
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

    async def _log(self, text: str):
        if self._config.log is not None:
            await self.send(build("PRIVMSG", [self._config.log, text]))
    async def _knag(self, oper: str, nick: str, kline_id: int):
        pref = await self.database.preference.get(oper, "knag")
        if pref == True: # == True because it could be None
            kline = await self.database.kline.get(kline_id)
            out = (
                f"k-line \2#{kline_id}\2 ({kline.mask}) set without a tag;"
                f" '/msg {self.nickname} ktag {kline_id} taghere' to tag it"
            )
            await self.send(build("NOTICE", [nick, out]))

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
                reason   = p_cliexit.group("reason")

                ip: Optional[Union[IPv4Address, IPv6Address]] = None
                if not (ip_str := p_cliexit.group("ip")) == "0":
                    ip = ipaddress.ip_address(ip_str)

                cliconn_id: Optional[int] = None
                if nickname in self._cliconns:
                    cliconn_id = self._cliconns.pop(nickname)

                await self.database.cliexit.add(
                    cliconn_id, nickname, username, hostname, ip, reason
                )

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

                for tag_match in (tags := list(RE_KLINETAG.finditer(reason))):
                    tag = tag_match.group(1)
                    if not await self.database.kline_tag.exists(id, tag):
                        await self.database.kline_tag.add(
                            id, tag, source, oper
                        )

                # if an existing k-line is being extended/updated, update
                # kills affected by the first k-line
                if old_id is not None:
                    db    = self.database
                    kills = await db.kline_kill.find_by_kline(old_id)
                    for kill in kills:
                        await db.kline_kill.set_kline(kill.id, id)

                if not tags:
                    await self._knag(oper, source.split("!", 1)[0], id)

                oper_colour = colourise(oper)
                await self._log(
                    f"KLINE:NEW: \2{id}\2 by {oper_colour}: {mask} {reason}"
                )

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
                    db = self.database
                    found = await db.kline_reject.find(
                        kline_id, nickname, username, hostname, ip
                    )
                    others = await db.kline_reject.find_by_hostname(
                        kline_id, hostname
                    )
                    if found is None and len(others) < self._config.rejects:
                        await self.database.kline_reject.add(
                            kline_id, nickname, username, hostname, ip
                        )

        elif (line.command == "PRIVMSG"
                and line.source is not None
                and not self.is_me(line.hostmask.nickname)):

            await self._on_message(line)

    async def _on_registration(
        self, nickname: str, account: str, email: str
    ) -> None:

        registration_id = await self.database.registration.add(
            nickname, account, email
        )

        email_parts = email.split("@", 1)
        if not len(email_parts) == 2:
            # log a warning?
            return

        _, email_domain = email_parts
        resolved = await recursive_mx_resolve(email_domain)

        resolved_ids: List[int] = []
        for record_parent, record_type, record in resolved:
            if record_parent is not None:
                record_parent = resolved_ids[record_parent]

            record_id = await self.database.email_resolve.add(
                registration_id, record_parent, record_type, record
            )
            resolved_ids.append(record_id)

    async def _on_message(self, line: Line) -> None:
        first, _, rest = line.params[1].partition(" ")
        if self.is_me(line.params[0]):
            # private message
            await self.cmd(
                line.hostmask,
                line.hostmask.nickname,
                first.lower(),
                rest,
                line.tags
            )
            return

        elif rest and first in {
            f"{self.nickname}{c}" for c in [":", ",", ""]
        }:
            # highlight in channel
            command, _, args = rest.partition(" ")
            await self.cmd(
                line.hostmask,
                line.params[0],
                command.lower(),
                args,
                line.tags
            )
            return

        message = f"{line.hostmask.nickname} {line.params[1]}"
        p_registration = RE_REGISTRAT.search(message)
        if p_registration is not None:
            nickname = p_registration.group("nickname")
            account = p_registration.group("account")
            email = p_registration.group("email")

            await self._on_registration(nickname, account, email)

    async def cmd(self,
            who:     Hostmask,
            target:  str,
            command: str,
            args:    str,
            tags:    Optional[Dict[str, str]]
            ):

        if tags and (oper := tags.get("solanum.chat/oper", "")):
            caller = Caller(who.nickname, str(who), oper)
            attrib = f"cmd_{command}"
            if hasattr(self, attrib):
                outs = await getattr(self, attrib)(caller, args)
                for out in outs:
                    await self.send(build("NOTICE", [target, out]))

    async def cmd_help(self, caller: Caller, args: str):
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

    async def _ktag(self,
            kline_id: int,
            tag:      str,
            caller:   Caller):

        if await self.database.kline_tag.exists(kline_id, tag):
            return [f"k-line {kline_id} is already tagged as '{tag}'"]
        else:
            await self.database.kline_tag.add(
                kline_id, tag, caller.source, caller.oper
            )
            kline = await self.database.kline.get(kline_id)
            kts   = pretty_delta(datetime.utcnow()-kline.ts)
            return [
                f"tagged {kts} old k-line"
                f" (#{kline_id} \2{kline.mask}\2) as {tag}"
            ]

    async def cmd_ktag(self, caller: Caller, sargs: str):
        args = sargs.split(None, 2)
        if len(args) < 2:
            return ["please provide a k-line ID and a tag"]
        elif not args[0].isdigit():
            return [f"'{args[0]}' doesn't look like a k-line ID"]
        elif not await self.database.kline.exists(kline_id := int(args[0])):
            return [f"k-line {kline_id} not found"]
        else:
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
        else:
            await self.database.kline_tag.remove(kline_id, tag)
            return [f"removed tag '{tag}' from k-line {kline_id}"]

    async def cmd_ktaglast(self, caller: Caller, sargs: str):
        args = sargs.split(None, 2)
        if len(args) < 2:
            return ["please provide a k-line count and tag"]
        elif not args[0].isdigit():
            return [f"'{args[0]}' isn't a number"]
        else:
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
            elif type == "mask":
                klines_ += await db.kline.find_by_mask_glob(query)
            elif type == "ts":
                if (dt := try_parse_ts(queryv)) is not None:
                    klines_ += await db.kline.find_by_ts(dt)
                else:
                    return [f"'{queryv}' does not look like a timestamp"]
            elif type == "tag":
                klines_ += await db.kline_tag.find(query)
            elif type == "id":
                if (query.isdigit()
                        and await db.kline.exists(query_id := int(query))):
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
                kline  = await db.kline.get(kline_id)
                remove = await db.kline_remove.get(kline_id)

                kts_human = pretty_delta(now-kline.ts)
                if remove is not None:
                    remover  = remove.oper or "unknown"
                    remove_s = f"\x0303removed\x03 by \x02{remover}\x02"
                elif kline.expire < now:
                    ts_since = pretty_delta(now-kline.expire)
                    remove_s = f"\x0303expired {ts_since} ago\x03"
                else:
                    ts_left  = pretty_delta(kline.expire-now)
                    remove_s = f"\x0304{ts_left} remaining\x03"

                kills   = await db.kline_kill.find_by_kline(kline_id)
                rejects = await db.kline_reject.find_by_kline(kline_id)
                affected: List[NickUserHost] = list(kills) + list(rejects)

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
        else:
            return ["please provide a type and query"]

    async def cmd_cliconn(self, caller: Caller, sargs: str):
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
                cliconn   = await db.cliconn.get(cliconn_id)
                cts_human = pretty_delta(now-cliconn.ts)
                nick_chg  = await db.nick_change.get(cliconn_id)

                outs.append(
                    f"\x02{cts_human}\x02 ago -"
                    f" {cliconn.nuh()} [{cliconn.realname}]"
                )
                if nick_chg:
                    nick_chg_s = ", ".join(nick_chg)
                    outs.append(f"  nicks: {nick_chg_s}")

            return outs or ["no results"]
        else:
            return ["please provide a type and query"]

    async def cmd_statsp(self, caller: Caller, args: str):
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

    async def cmd_pref(self, caller: Caller, sargs: str):
        args = sargs.split(None, 1)
        db   = self.database
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
        else:
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

