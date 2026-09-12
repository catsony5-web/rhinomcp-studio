# Recover without repeating uncertain edits

Managed releases require the configured management service to approve every new
Rhino command. A `management_denied` response means that command was refused before
execution. Read `get_management_status` for local registration and the last reason;
it remains available alongside `describe_capabilities` during maintenance. Report
the reason and let the administrator resume service or supply an approved update.
Do not bypass maintenance with direct sockets, scripts, a changed service URL,
deleted configuration or an older plugin. A network failure can cause the same
refusal: manual Rhino editing and saving are still available. Local status never
grants permission for the next command; each command obtains a fresh approval.

For a missing Studio bridge, confirm that the Studio plugin is loaded using its
Rhino command StudioMCPVersion and start it with StudioMCPStart when needed.
StudioMCPStop stops that bridge. Do not substitute generic mcpstart/mcpstop:
another installed plugin can own those names. Diagnose the intended endpoint
127.0.0.1:1999 and version rather than accepting another server's start message.

After an error, lost connection or interrupted session, inspect the active document,
known object IDs and current geometry before retrying a mutation. An interrupted
response does not prove that Rhino did not execute the operation. Blind repetition
can create duplicates or transform an object twice.

Distinguish invalid inputs, unsupported operations, transport failures, incorrect
modeling choices and suspected tool defects. Read tool errors and compare the saved
or live geometry with the request. Keep failed artifacts or diagnostic screenshots
when they are useful; do not label a failed result as accepted.

Limit cleanup to objects known to belong to this task. Do not delete unrelated,
hidden or locked user work. If ownership is uncertain, stop the destructive cleanup
and clarify the affected objects. Preserve the user's document rather than resetting
it to make an experiment succeed.

If retrying, use the observed state and a bounded plan. Verify after each uncertain
step. Do not change the required geometry, relax tolerances, or omit a failed check
just to obtain a passing result. Plugin rebuilding, automatic installation and
experimental baseline replacement belong to the contributor harness, not a normal
modeling session.
