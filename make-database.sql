-- 16  is nickname length
-- 10  is username length
-- 50  is realname length
-- 64  is hostname length
-- 90  is mask length
-- 260 is reason length

BEGIN;

CREATE TABLE kline (
    id       SERIAL PRIMARY KEY,
    mask     VARCHAR(90)  NOT NULL,
    source   VARCHAR(90)  NOT NULL,
    oper     VARCHAR(16)  NOT NULL,
    duration INT          NOT NULL,
    reason   VARCHAR(260) NOT NULL,
    ts       TIMESTAMP    NOT NULL,
    expire   TIMESTAMP    NOT NULL
);

CREATE TABLE kline_remove (
    kline_id INTEGER     NOT NULL  PRIMARY KEY  REFERENCES kline (id)  ON DELETE CASCADE,
    source   VARCHAR(90),
    oper     VARCHAR(16),
    ts       TIMESTAMP   NOT NULL
);

CREATE TABLE kline_kill (
    id          SERIAL PRIMARY KEY,
    kline_id    INTEGER     NOT NULL  REFERENCES kline (id)  ON DELETE CASCADE,
    nickname    VARCHAR(16) NOT NULL,
    search_nick VARCHAR(16) NOT NULL,
    username    VARCHAR(10) NOT NULL,
    search_user VARCHAR(10) NOT NULL,
    hostname    VARCHAR(64) NOT NULL,
    search_host VARCHAR(64) NOT NULL,
    ip          INET,
    ts          TIMESTAMP   NOT NULL
);

CREATE TABLE cliconn (
    id          SERIAL PRIMARY KEY,
    nickname    VARCHAR(16) NOT NULL,
    search_nick VARCHAR(16) NOT NULL,
    username    VARCHAR(10) NOT NULL,
    search_user VARCHAR(10) NOT NULL,
    realname    VARCHAR(50) NOT NULL,
    search_real VARCHAR(50) NOT NULL,
    hostname    VARCHAR(64) NOT NULL,
    search_host VARCHAR(64) NOT NULL,
    ip          INET,
    ts          TIMESTAMP   NOT NULL
);

CREATE TABLE statsp (
    oper VARCHAR(16) NOT NULL,
    mask VARCHAR(90) NOT NULL,
    ts   TIMESTAMP   NOT NULL,
    PRIMARY KEY (mask, ts)
);


-- to speed up searches
CREATE INDEX kline_kill_search_nick ON kline_kill(search_nick);
CREATE INDEX kline_kill_search_user ON kline_kill(search_user);
CREATE INDEX kline_kill_search_host ON kline_kill(search_host);
CREATE INDEX kline_kill_ip          ON kline_kill(ip);
CREATE INDEX cliconn_search_nick    ON cliconn(search_nick);
CREATE INDEX cliconn_search_user    ON cliconn(search_user);
CREATE INDEX cliconn_search_host    ON cliconn(search_host);
CREATE INDEX cliconn_ip             ON cliconn(ip);
CREATE INDEX statsp_oper            ON statsp(oper);

-- to speed up bulk/cascaded deletions of klines past retention period
CREATE INDEX kline_expire           ON kline(expire);
CREATE INDEX kline_kill_kline_id    ON kline_kill(kline_id);
CREATE INDEX kline_remove_kline_id  ON kline_remove(kline_id);

COMMIT;
