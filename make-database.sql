PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE klines (
    id        INTEGER PRIMARY KEY,
    mask      TEXT NOT NULL,
    setter    TEXT NOT NULL,
    duration  INTEGER NOT NULL,
    reason    TEXT NOT NULL,
    ts        INTEGER NOT NULL,
    remove_by TEXT,
    remove_at INT
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
COMMIT;
