# beryllia

collection of rich and searchable IRC oper data

## setup

```
$ cp config.example.yaml config.yaml
$ vim config.yaml
$ psql < make-database.sql
```

## running

```
$ python3 -m beryllia config.yaml
```

## k-line tracking (`!kcheck`)

beryllia will watch for k-lines and watch for connections being affected by
k-lines, then allow you to search k-lines by various data points.

k-line masks are treated as opaque strings, and because of this searches are
usually performed against connections that have been affected by k-lines,
rather than the k-lines themselves, because connections have discrete
attributes; i.e. nick, user, host, ip, etc. this detail is mostly esoteric to
end users, but is vital when understanding how `!kcheck` works.

### command

```
<jess> kcheck nick jess-*
-beryllia- affected: jess-test!~j@sandcat.libera.chat
-beryllia-   K-Line: *@198.51.100.123 5s ago by jess for 1 mins (54s remaining) test please ignore
<jess> kcheck host *.libera.chat
-beryllia- affected: jess-test!~j@sandcat.libera.chat
-beryllia-   K-Line: *@198.51.100.123 11s ago by jess for 1 mins (48s remaining) test please ignore
<jess> kcheck ip 198.51.100.*
-beryllia- affected: jess-test!~j@sandcat.libera.chat
-beryllia-   K-Line: *@198.51.100.123 1m38s ago by jess for 1 mins (30s remaining) test please ignore
<jess> kcheck ip 198.51.100.0/24
-beryllia- affected: jess-test!~j@sandcat.libera.chat
-beryllia-   K-Line: *@198.51.100.123 1m38s ago by jess for 1 mins (12s remaining) test please ignore
```

each category (`nick`, `host`, `ip`) supports globs; `ip` also supports CIDRs.

### data

#### active connections being killed by a k-line

consider the following
```
:lithium NOTICE * :*** Notice -- sandcat!jess@libera/staff/cat/jess{jess} added global 1 min. K-Line for [*@198.51.100.123] [test please ignore]
:lithium NOTICE * :*** Notice -- Disconnecting K-Lined user jess-test[~j@sandcat.libera.chat] (*@198.51.100.123)
:lithium NOTICE * :*** Notice -- Client exiting: jess-test (~j@sandcat.libera.chat) [K-Lined] [198.51.100.123]
```

we save the k-line attributes from the first snote to the database's `kline`
table. we then match the second and third snote together (because the second
mightn't've had the user's IP in it (rDNS or cloak)) to gather the discrete
attributes of the connection, then we get the k-line mask (`*@198.51.100.123`)
from the second snote and find it's `kline_id` in the `kline` table, then save
the connection's attributes to the `kline_kill` table, tagged with that
`kline_id`.

#### new connections being rejected due to a k-line

consider the following
```
:lithium NOTICE * :*** Notice -- sandcat!jess@libera/staff/cat/jess{jess} added global 1 min. K-Line for [*@198.51.100.123] [test please ignore]
```

and then consider the following happens 20 minutes later
```
:lithium NOTICE * :*** Notice -- Rejecting K-Lined user jess-test[~j@sandcat.libera.chat] [198.51.100.123] (*@198.51.100.123)
```

similar to the above, but this snote has the user's IP in it in a discrete
field so we only need to match this one snote against an active k-line mask.
we take the k-line mask (`*@198.51.100.123`), find it's `kline_id` from the
`kline` table, then save the rejected connection's attributes to the
`kline_reject` table, tagged with that `kline_id`.
