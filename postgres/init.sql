DO
$$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_database WHERE datname = 'smart_agent'
   ) THEN
      CREATE DATABASE smart_agent;
   END IF;
END
$$;
