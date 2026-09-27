CREATE TABLE aggregates (
  week TEXT NOT NULL,
  dimension TEXT NOT NULL CHECK (dimension IN ('total','variant','flavor','arch','age_bucket')),
  category TEXT NOT NULL,
  count INTEGER NOT NULL CHECK (count >= 0),
  PRIMARY KEY (week, dimension, category)
) WITHOUT ROWID;
CREATE TABLE heartbeats (hour TEXT PRIMARY KEY) WITHOUT ROWID;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE snapshots (week TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
