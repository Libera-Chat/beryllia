-- 16  is nickname length
-- 10  is username length
-- 32  is kline tag length
-- 50  is realname length
-- 64  is hostname length
-- 92  is mask length
-- 260 is reason length

BEGIN;

CREATE TABLE kline (
    id          SERIAL PRIMARY KEY,
    mask        VARCHAR(92)  NOT NULL,
    search_mask VARCHAR(92)  NOT NULL,
    source      VARCHAR(92)  NOT NULL,
    oper        VARCHAR(16)  NOT NULL,
    duration    INT          NOT NULL,
    reason      VARCHAR(260) NOT NULL,
    ts          TIMESTAMP    NOT NULL,
    expire      TIMESTAMP    NOT NULL
);
-- for retention period bulk deletion
CREATE INDEX kline_expire ON kline(expire);
-- for database.kline.find()
CREATE INDEX kline_mask   ON kline(mask);

CREATE TABLE kline_remove (
    kline_id INTEGER     NOT NULL  PRIMARY KEY  REFERENCES kline (id)  ON DELETE CASCADE,
    source   VARCHAR(92),
    oper     VARCHAR(16),
    ts       TIMESTAMP   NOT NULL
);
-- for joining with kline(id)
CREATE INDEX kline_remove_kline_id ON kline_remove(kline_id);

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
-- for joining with kline(id)
CREATE INDEX kline_kill_kline_id    ON kline_kill(kline_id);
-- for `!kcheck` searches
CREATE INDEX kline_kill_search_nick ON kline_kill(search_nick);
CREATE INDEX kline_kill_search_user ON kline_kill(search_user);
CREATE INDEX kline_kill_search_host ON kline_kill(search_host);
CREATE INDEX kline_kill_ip          ON kline_kill(ip);

CREATE TABLE kline_reject (
    id          SERIAL PRIMARY KEY,
    kline_id    INTEGER     NOT NULL  REFERENCES kline (id)  ON DELETE CASCADE,
    nickname    VARCHAR(16) NOT NULL,
    search_nick VARCHAR(16) NOT NULL,
    username    VARCHAR(10) NOT NULL,
    search_user VARCHAR(10) NOT NULL,
    hostname    VARCHAR(64) NOT NULL,
    search_host VARCHAR(64) NOT NULL,
    ip          INET,
    ts          TIMESTAMP   NOT NULL,
    UNIQUE (kline_id, search_nick, search_user, search_host)
);
-- for joining with kline(id)
CREATE INDEX kline_reject_kline_id    ON kline_reject(kline_id);
-- for `!kcheck` searches
CREATE INDEX kline_reject_search_nick ON kline_reject(search_nick);
CREATE INDEX kline_reject_search_user ON kline_reject(search_user);
CREATE INDEX kline_reject_search_host ON kline_reject(search_host);
CREATE INDEX kline_reject_ip          ON kline_reject(ip);

CREATE TABLE kline_tag (
    kline_id    INTEGER      NOT NULL  REFERENCES kline (id)  ON DELETE CASCADE,
    tag         VARCHAR(32)  NOT NULL,
    search_tag  VARCHAR(32)  NOT NULL,
    source      VARCHAR(92)  NOT NULL,
    oper        VARCHAR(16)  NOT NULL,
    ts          TIMESTAMP    NOT NULL,
    PRIMARY KEY (kline_id, search_tag)
);
-- for `!kcheck` searches
CREATE INDEX kline_tag_search_tag ON kline_tag (search_tag);

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
    account     VARCHAR(16),
    search_acc  VARCHAR(16),
    ip          INET,
    server      VARCHAR(92) NOT NULL,
    ts          TIMESTAMP   NOT NULL
);
-- for retention period bulk deletion
CREATE INDEX cliconn_ts          ON cliconn(ts);
-- for `!cliconn` searches
CREATE INDEX cliconn_search_nick ON cliconn(search_nick);
CREATE INDEX cliconn_search_user ON cliconn(search_user);
CREATE INDEX cliconn_search_host ON cliconn(search_host);
CREATE INDEX cliconn_ip          ON cliconn(ip);

CREATE TABLE cliexit (
    cliconn_id  INTEGER    PRIMARY KEY  NOT NULL  REFERENCES cliconn(id),
    ts          TIMESTAMP  NOT NULL
);

CREATE TABLE nick_change (
    id           SERIAL       PRIMARY KEY,
    cliconn_id   INTEGER      NOT NULL  REFERENCES cliconn (id)  ON DELETE CASCADE,
    nickname     VARCHAR(16)  NOT NULL,
    search_nick  VARCHAR(16)  NOT NULL,
    ts           TIMESTAMP    NOT NULL
);
-- for `!cliconn` searches
CREATE INDEX nick_change_cliconn_id ON nick_change(cliconn_id);
CREATE INDEX nick_change_nickname   ON nick_change(nickname);

CREATE TABLE statsp (
    oper VARCHAR(16) NOT NULL,
    mask VARCHAR(92) NOT NULL,
    ts   TIMESTAMP   NOT NULL,
    PRIMARY KEY (mask, ts)
);
CREATE INDEX statsp_ts ON statsp(ts);

CREATE TABLE preference (
    oper   VARCHAR(16)   NOT NULL,
    key    VARCHAR(32)   NOT NULL,
    value  VARCHAR(260)  NOT NULL
);

COMMIT;
