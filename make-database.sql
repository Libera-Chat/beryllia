PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE klines (
    id       INTEGER PRIMARY KEY,
    mask     TEXT NOT NULL,
    source   TEXT NOT NULL,
    oper     TEXT NOT NULL,
    duration INTEGER NOT NULL,
    reason   TEXT NOT NULL,
    ts       INTEGER NOT NULL,
    expire   INTEGER NOT NULL
);
CREATE TABLE kline_removes (
    id     INTEGER NOT NULL,
    source TEXT,
    oper   TEXT,
    ts     INTEGER NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (id) REFERENCES klines(id)
);
CREATE TABLE kline_rejects (
    nickname    TEXT NOT NULL,
    search_nick TEXT NOT NULL,
    username    TEXT NOT NULL,
    search_user TEXT NOT NULL,
    hostname    TEXT NOT NULL,
    search_host TEXT NOT NULL,
    ip          TEXT,
    kline_id    INTEGER NOT NULL,
    PRIMARY KEY (search_nick, search_user, search_host, ip, kline_id),
    FOREIGN KEY (kline_id) REFERENCES klines(id)
);
CREATE TABLE kline_kills (
    id          INTEGER PRIMARY KEY,
    nickname    TEXT NOT NULL,
    search_nick TEXT NOT NULL,
    username    TEXT NOT NULL,
    search_user TEXT NOT NULL,
    hostname    TEXT NOT NULL,
    search_host TEXT NOT NULL,
    ip          TEXT,
    ts          INTEGER NOT NULL,
    kline_id    INTEGER,
    FOREIGN KEY(kline_id) REFERENCES klines(id)
);

CREATE INDEX kills_search_nick   ON kline_kills(search_nick);
CREATE INDEX kills_search_user   ON kline_kills(search_user);
CREATE INDEX kills_search_host   ON kline_kills(search_host);
CREATE INDEX kills_ip            ON kline_kills(ip);

CREATE INDEX rejects_search_nick ON kline_rejects(search_nick);
CREATE INDEX rejects_search_user ON kline_rejects(search_user);
CREATE INDEX rejects_search_host ON kline_rejects(search_host);
CREATE INDEX rejects_ip          ON kline_rejects(ip);

COMMIT;
