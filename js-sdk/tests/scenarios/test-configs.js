const TEST_CONFIG = {
  DATASITE: "khoa@openmined.org",
};

module.exports = {
  DATASITE: process.env.DATASITE || TEST_CONFIG.DATASITE,
};
