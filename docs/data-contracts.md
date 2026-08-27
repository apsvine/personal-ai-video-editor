# Future data contracts

No pipeline stages or production schemas are implemented in Phase 00.

Future expensive stages will save their results as **versioned JSON files**
in local project runtime storage. Completed outputs must be reusable after a
failure instead of recalculating every preceding stage.

When a stage is implemented, its contract should define a schema version,
stage identity, input identity/fingerprint, relevant configuration and
provider/tool version, completion status, and output references. Exact field
names and schemas must be agreed in that stage's phase, not invented here.

Consumers should validate schema compatibility and input/configuration
identity before reuse. Failed or partial writes must not appear as completed
artifacts; use atomic publication and keep the last valid result available.
Invalidation should affect changed inputs and their downstream dependents,
not unrelated successful stages. Corrections should retain enough provenance
to explain which artifacts were reused or regenerated.

Store media separately and reference local files instead of embedding binary
data in JSON. Keep credentials out of artifacts and logs. Runtime artifacts
are private user data and must not enter Git. Tests may later use tiny,
intentional sanitized fixtures.
