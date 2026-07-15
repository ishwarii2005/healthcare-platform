# Google Calendar Setup

This platform uses **one clinic Google account**, connected once by the admin,
rather than requiring every doctor and patient to do their own OAuth. Appointments
are created as a single event on that clinic calendar with the doctor and patient
added as attendees — both get a normal Calendar invite in their own calendars.

## 1. Create a Google Cloud project

1. Go to https://console.cloud.google.com/ and create a new project (or reuse one).
2. In the left menu, go to **APIs & Services → Library**, search for **Google Calendar API**, and click **Enable**.

## 2. Configure the OAuth consent screen

1. **APIs & Services → OAuth consent screen**.
2. User type: **External** (fine for a POC — you'll add your clinic Gmail as a test user).
3. Fill in app name (e.g. "City Care Clinic"), support email, and developer contact email.
4. Scopes: add `https://www.googleapis.com/auth/calendar`.
5. Test users: add the Google account you'll use as the clinic's calendar (e.g. `clinic@gmail.com`).
6. Save.

## 3. Create OAuth credentials

1. **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
2. Application type: **Web application**.
3. Authorized redirect URIs — add both, so it works locally and once deployed:
   - `http://localhost:8000/api/calendar/oauth/callback`
   - `https://<your-backend>.onrender.com/api/calendar/oauth/callback`
4. Click **Create**. Copy the **Client ID** and **Client Secret** into your backend `.env`:
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REDIRECT_URI=http://localhost:8000/api/calendar/oauth/callback
   ```

## 4. Connect the clinic calendar from the app

1. Log in to the app as an **admin**.
2. Go to **Admin portal → Google Calendar → Connect Google Calendar**.
3. You'll be redirected to Google's consent screen. Log in with the clinic account
   you added as a test user, and approve the calendar scope.
4. Google redirects back to `/api/calendar/oauth/callback`, which stores a refresh
   token in the `calendar_credentials` table. The admin page will now show
   "Clinic calendar is connected."

## 5. Verify

Book a test appointment as a patient. Once the symptom form is submitted (which
confirms the booking), check the clinic Google account's calendar — you should see
a new event with both the doctor and patient listed as attendees, and both should
receive a Calendar invite email.

## Notes

- `CLINIC_CALENDAR_ID=primary` uses the connected account's main calendar. To use a
  dedicated calendar instead, create one in Google Calendar, find its Calendar ID
  under **Settings → Integrate calendar**, and set `CLINIC_CALENDAR_ID` to that value.
- If the calendar is never connected, or a Calendar API call fails for any reason,
  booking still succeeds — the appointment simply has no calendar event and a
  warning is logged. This is intentional (see `docs/SYSTEM_DESIGN.md`): calendar
  and email delivery must never block the core booking flow.
- Google's OAuth **External + Testing** mode refresh tokens can expire after ~7 days
  of inactivity. For anything beyond a POC demo, either publish the OAuth consent
  screen (removes the 7-day limit) or reconnect periodically from the admin page.
