# beryllia

track when and why users were affected by k-lines

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

## how does this work

consider the following

```
:lithium NOTICE * :*** Notice -- sandcat!jess@libera/staff/cat/jess{jess} added global 1 min. K-Line for [*@1.2.3.4] [test please ignore]
:lithium NOTICE * :*** Notice -- KLINE active for jess-test[~j@sandcat.libera.chat] (*@1.2.3.4)
:lithium NOTICE * :*** Notice -- Client exiting: jess-test (~j@sandcat.libera.chat) [K-Lined] [1.2.3.4]
```

we match the second and third snote together to find the user's IP, because
the second mightn't've had the user's IP in it (rDNS or cloak) then we match
the k-line mask (`*@1.2.3.4`) from the second snote to the mask from the first
snote, and those all tie together to both give us info to search for users
(nick, host, ip) and info on the k-line (setter, duration, reason)

## todo

it'd be nice to be able to search k-lines as well as searching for users
killed by k-lines, so we can find k-lines set by Ozone, who `KILL`s users
before a k-line can.

we should read `STATS g` when we boot up to see if anything we saw get set has
been unset while we were offline.
