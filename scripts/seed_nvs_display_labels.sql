-- Facility short labels for NVS terms (L22 device catalogue, B76 platform models).
--
-- nvs_terms.pref_label mirrors the canonical NVS skos:prefLabel and is
-- refreshed on every sync_nvs_terms.py run, so it must not be hand-edited.
-- display_label is the facility's chosen short form; the sync script never
-- touches it. nvs_terms.label (generated) = COALESCE(display_label, pref_label)
-- and is what the portal and the Slocum pipeline's deployment.yml read.
--
-- Keyed by uri (the natural key) so it is safe on any snapshot regardless
-- of surrogate ids. Idempotent: re-running just re-asserts the same values.
-- Edit a label here, re-run, commit -- this file is the source of truth.

UPDATE nvs_terms t SET display_label = v.display_label
FROM (VALUES
    -- L22 -- sensor make + model (deployment.yml glider_devices.*.make_model)
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL0215/', 'WET Labs ECO FLNTU'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL0669/', 'Sea-Bird SBE 41CP'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL0836/', 'Aanderaa 3830 optode'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL1026/', 'Sea-Bird GPCTD'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL1188/', 'Sea-Bird CT Sail'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL1232/', 'Rockland MicroRider-1000'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL1239/', 'Aanderaa 4831 optode'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL1240/', 'Aanderaa 4831F optode'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL1247/', 'Aanderaa 4330 optode'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL1248/', 'Aanderaa 4330F optode'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL1310/', 'WET Labs ECO Triplet BB2FL-VMT'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL1312/', 'WET Labs ECO Triplet FLBBCD-SLC'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL1492/', 'Sea-Bird Slocum GPCTD'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL1745/', 'RBR Legato3'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL1993/', 'WET Labs ECO Puck FLNTU-SLK'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL2257/', 'WET Labs ECO Puck FLNTU-SLC'),
    ('http://vocab.nerc.ac.uk/collection/L22/current/TOOL2261/', 'RBR Legato4'),

    -- B76 -- platform model (deployment.yml metadata.glider_model; portal
    -- glider "platformModelFull"). Canonical is e.g. "Teledyne Webb Research
    -- Slocum G1 glider" -- fine in a catalogue, too long for a NetCDF attr.
    ('http://vocab.nerc.ac.uk/collection/B76/current/B7600013/', 'Slocum G1'),
    ('http://vocab.nerc.ac.uk/collection/B76/current/B7600001/', 'Slocum G2'),
    ('http://vocab.nerc.ac.uk/collection/B76/current/B7600014/', 'Slocum G3'),
    ('http://vocab.nerc.ac.uk/collection/B76/current/B7600029/', 'Slocum G3S'),
    ('http://vocab.nerc.ac.uk/collection/B76/current/B7600024/', 'Seaglider M1'),
    ('http://vocab.nerc.ac.uk/collection/B76/current/B7600034/', 'Seaglider SGX')
) AS v(uri, display_label)
WHERE t.uri = v.uri;
