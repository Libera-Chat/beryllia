PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE klines (
    id       INTEGER PRIMARY KEY,
    mask     TEXT NOT NULL,
    source   TEXT NOT NULL,
    oper     TEXT NOT NULL,
    duration INTEGER NOT NULL,
    reason   TEXT NOT NULL,
    ts       INTEGER NOT NULL
);
CREATE TABLE kline_removes (
    id     INTEGER NOT NULL,
    source TEXT,
    oper   TEXT,
    ts     INTEGER NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (id) REFERENCES klines(id)
);
CREATE TABLE kills (
    nickname    TEXT NOT NULL,
    search_nick TEXT NOT NULL,
    username    TEXT NOT NULL,
    search_user TEXT NOT NULL,
    hostname    TEXT NOT NULL,
    search_host TEXT NOT NULL,
    ip          TEXT NOT NULL,
    ts          INTEGER NOT NULL,
    kline_id    INTEGER,
    FOREIGN KEY(kline_id) REFERENCES klines(id)
);

CREATE INDEX kills_nickname    ON kills(nickname);
CREATE INDEX kills_ts          ON kills(ts);
CREATE INDEX kills_search_nick ON kills(search_nick);
CREATE INDEX kills_search_user ON kills(search_user);
CREATE INDEX kills_search_host ON kills(search_host);

COMMIT;
