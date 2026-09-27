# Tools

Use the installed bodybrain skill and its scripts/bodybrain_client.py helper.
Runtime environment supplies BODYBRAIN_BACKEND_URL and BODYBRAIN_AGENT_TOKEN.
Never read or print secret values. The helper handles the Authorization header.

Only fetch the supplied task, search anatomy, and submit that task result.
Use a JSON file for results; do not interpolate source text into shell commands.
Do not call messaging tools or unrelated network endpoints.
