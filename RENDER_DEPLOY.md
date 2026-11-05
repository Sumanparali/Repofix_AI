# Render demo deployment

This Blueprint deploys RepoFix as an analysis-only demo with one Free web service and one Free
PostgreSQL database. The web service uses the in-process queue, so Redis and a separate worker are
not required.

## Required Blueprint values

Render prompts for these Firebase client configuration values during Blueprint creation:

- `FIREBASE_API_KEY`
- `FIREBASE_AUTH_DOMAIN`
- `FIREBASE_PROJECT_ID`
- `FIREBASE_APP_ID`

Copy their values from the local `.env` file. Do not commit `.env`.

## Required secret file

After Render creates the web service, open **Environment**, select **Add Secret File**, and add:

- Filename: `firebase-admin.json`
- Contents: the complete contents of the local `secrets/firebase-admin.json` file

Render exposes the file at `/etc/secrets/firebase-admin.json`, matching
`GOOGLE_APPLICATION_CREDENTIALS` in the Blueprint.

## Firebase authorized domain

After the first successful deploy, copy the service hostname (for example,
`repofix-ai.onrender.com`) and add it in Firebase Console under **Authentication > Settings >
Authorized domains**.

## Free-tier limitations

- The web service sleeps after 15 minutes without inbound traffic and can take about one minute to
  wake up.
- Its filesystem is ephemeral. Repository workspaces are temporary by design.
- A Free Render PostgreSQL database expires 30 days after creation and has no backups. Upgrade or
  export the data before expiry if it must be retained.
