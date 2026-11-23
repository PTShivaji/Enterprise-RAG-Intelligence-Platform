-- Runs once, on first initialisation of the Postgres data volume.
-- Enables pgvector in the application database and creates a separate test database.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE DATABASE rag_test OWNER rag;
\connect rag_test
CREATE EXTENSION IF NOT EXISTS vector;
