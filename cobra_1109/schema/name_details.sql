-- Run once per office database.
CREATE TABLE IF NOT EXISTS name_details (
  NameID       VARCHAR(50)  NOT NULL PRIMARY KEY,
  Name         VARCHAR(50)  NOT NULL,
  Rank         VARCHAR(50),
  IDnumber     VARCHAR(50),
  Section      VARCHAR(50),
  Gender       VARCHAR(255),
  PasswordHash VARCHAR(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
