# RepoFix authentication setup

PostgreSQL is already installed in `docker-compose.yml` and starts automatically.
RepoFix currently runs with `REPOFIX_AUTH_MODE=local` until Firebase is configured.

## 1. Create Firebase

1. Open https://console.firebase.google.com/ and create a project.
2. Open **Authentication → Sign-in method**.
3. Enable **Email/Password**, **Google**, and optionally **GitHub**.
4. Open **Project settings → Your apps → Web app** and copy the web configuration.

## 2. Add these values to `.env`

Copy the missing variables from `.env.example` into `.env` and fill them:

```env
REPOFIX_AUTH_MODE=firebase
FIREBASE_API_KEY=your-api-key
FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_APP_ID=your-app-id
```

Also change `POSTGRES_PASSWORD` from the local default to a strong password before deployment.

## 3. Add the backend credential

1. In Firebase open **Project settings → Service accounts**.
2. Select **Generate new private key**.
3. Create a `secrets` folder in this project and save the file as:
   `secrets/firebase-admin.json`
4. Do not commit that file. The `secrets/` folder is already ignored by Git.
5. Add to `.env`:

```env
GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/firebase-admin.json
```

6. Add this read-only mount under the Compose `api` service if Firebase mode is enabled:

```yaml
volumes:
  - ./secrets/firebase-admin.json:/run/secrets/firebase-admin.json:ro
```

Keep the existing API volumes too.

## 4. Restart

```powershell
docker compose up --build -d
```

Open http://127.0.0.1:8000/login.

The API endpoint `GET /api/auth/config` should then return `"enabled": true`.

## Security rules

- Never put the service-account JSON in frontend code.
- Never commit `.env` or the `secrets/` folder.
- Firebase stores passwords; PostgreSQL stores users, job ownership, and job results.
- Every `/api/jobs` endpoint verifies the Firebase token and filters jobs by user.
