-- Extensions used by the schema (see docs/database-design.md).
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- fuzzy search on names / serials
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- exclusion constraints (appointment overlap)
CREATE EXTENSION IF NOT EXISTS unaccent;     -- accent-insensitive full-text search
