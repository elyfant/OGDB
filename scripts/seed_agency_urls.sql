-- agencies.url -- each agency's homepage.
--
-- Feeds the Slocum pipeline's config.resolve() (creator_url / publisher_url,
-- falling back to this when the PI has no personal webpage) and gives the
-- portal something to link an agency to.
--
-- Keyed by agencies.name (the short code, unique in practice). Idempotent.
-- Only fill in a URL once it's actually confirmed -- leave NULL otherwise
-- (resolve() falls back further to the facility default in that case).

UPDATE agencies i SET url = v.url
FROM (VALUES
    ('UIB', 'https://norgliders.gfi.uib.no/')
) AS v(name, url)
WHERE i.name = v.name;
