-- Backfill mission_sea_names from mission.site, C19-only.
-- Idempotent (ON CONFLICT DO NOTHING). Confident site->sea mappings only;
-- ambiguous sites (DML, Northsvalbard, Porsangerfjorden, SOP, Svalbard) and
-- non-sea sites (Hornindalsvatn = lake, Masfjorden = fjord) are left for
-- manual review.
INSERT INTO mission_sea_names (mission_id, c19_term_id)
SELECT m.id, t.id
FROM missions m
JOIN sites s   ON s.id = m.site_id
JOIN LATERAL (VALUES
    ('Baffin',        'C19/current/9_12/'),
    ('barents',       'C19/current/9_4/'),
    ('Faroe',         'C19/current/9_7/'),
    ('Fram',          'C19/current/FRAM/'),
    ('Gimsoy',        'C19/current/9_7/'),
    ('Greenland',     'C19/current/9_6/'),
    ('Iceland',       'C19/current/9_8/'),
    ('Lofoten',       'C19/current/9_7/'),
    ('Mediterranean', 'C19/current/3_1/'),
    ('Mohn',          'C19/current/9_7/'),
    ('Norwegian',     'C19/current/9_7/'),
    ('Svinoy',        'C19/current/9_7/'),
    ('WSC',           'C19/current/FRAM/')
) map(site_name, uri_frag) ON s.name = map.site_name
JOIN nvs_terms t ON t.uri LIKE '%' || map.uri_frag
ON CONFLICT (mission_id, c19_term_id) DO NOTHING;
