\set ON_ERROR_STOP on

\if :{?claro_password}
\else
  \echo 'Set the claro_password psql variable before running this script.'
  \quit 1
\endif

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'app_role', :'claro_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_role')
\gexec

SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'app_role', :'claro_password')
\gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'db_name', :'app_role')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name')
\gexec

SELECT format('ALTER DATABASE %I OWNER TO %I', :'db_name', :'app_role')
\gexec

\connect :db_name
GRANT CONNECT ON DATABASE :db_name TO :app_role;
GRANT USAGE, CREATE ON SCHEMA public TO :app_role;
ALTER SCHEMA public OWNER TO :app_role;
