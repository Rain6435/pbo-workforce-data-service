-- Runs once, when the compose db volume is first created. The test suite
-- needs its own database (its name must end in _test: tests/conftest.py
-- resets the schema at the start of every run).
CREATE DATABASE pbo_workforce_test OWNER pbo_admin;
