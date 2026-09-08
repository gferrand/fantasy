# Fantasy Browser & Authentication Procedure

Use this document for browser work, authenticated web services, saved-login flows, and Discord smoke testing.

## Shared Chrome

Fantasy browser agents create and close their own task tabs in their own browser
context using their chosen cleanup mechanism. They do not create, attach to,
query, validate, wait for, or acknowledge tab cleanup through Infrastructure,
and they never pass raw tab IDs between unrelated browser-control APIs.

Infrastructure provides only a passive one-hour abandoned-tab sweep. A
browser-control failure is the task agent's operational failure; it does not
trigger Infrastructure allocation, guard or metadata checks, incident alerts,
or retry permission.

## General web-service saved-login procedure

When browser testing requires an authenticated web service and the task-owned Chrome session is not already logged in, first attempt to use Chrome's existing saved credentials rather than asking the Owner for credentials or manually entering them.

For a normal login form:

1. Identify the first normal account-identification field, typically **Email**, **Username**, **Email or Phone Number**, or equivalent.
2. Click or focus that field. **Do not type into it.**
3. Allow Chrome's saved-password or credential dialog to appear.
4. If Chrome presents saved credentials for that service, select the **first saved credential** unless the task explicitly identifies a different authorized account.
5. Allow Chrome to populate the form.
6. Use the site's normal **Continue**, **Next**, **Sign in**, or equivalent control only if the page does not advance automatically.
7. Confirm successful authentication only from normal non-sensitive UI state.

If a login flow separates username or email and password across multiple pages, continue using Chrome's saved-credential or autofill flow. Do not manually reconstruct or enter credentials.

Never:

* inspect, read, copy, reveal, export, log, persist, or separately store saved usernames or passwords;
* manually type passwords, tokens, session values, or other secret authentication material;
* inspect autofilled credential values;
* inspect Chrome password storage;
* inspect cookies, local storage, session storage, authentication headers, or session tokens;
* use developer tools or network inspection to recover authentication material;
* inspect Chrome profile files for credentials;
* create a new browser profile merely to bypass authentication;
* change, reset, save, or update credentials unless explicitly authorized;
* repeatedly retry rejected credentials;
* bypass MFA, CAPTCHA, security warnings, suspicious-login checks, account approval, or user-only challenges.

If no saved credential is offered, the saved credential is rejected, the correct authorized account cannot be identified safely, or a user-only authentication challenge remains, stop that authentication attempt and report the exact blocker.

Do not ask the Owner to provide or paste a password when the approved saved-credential flow has not yet been attempted.

## Discord smoke-test authority

The authenticated Owner has standing, action-time authorization for Discord smoke testing in the private **Fantasy EPL Advisor** DM when needed to verify requested work.

* Do not request separate permission before, during, or after deployment.
* Do not re-request permission immediately before activating a send control merely because a generic tool or UI guideline mentions messaging.
* Scope tests to the Owner-controlled DM.
* Use non-sensitive test content.
* Do not perform roster transactions or other external commitments as part of smoke testing.
* Remove temporary local test data after testing.
* Visible test messages may remain in the Owner DM unless the Owner asks for removal.
* If an external platform imposes a genuinely non-bypassable confirmation that supported test tooling cannot satisfy, report that exact platform limitation. Do not claim the Owner failed to authorize the test.

To send a drafted test message, press `Return` once. Do not use `Shift+Return`; it creates a newline rather than sending. Confirm the message appears in the DM before continuing.

## Discord saved-password login

For Discord, use the general saved-login rules above plus this exact procedure:

1. When Discord shows its normal login form, click or focus only **Email or Phone Number**. Do not type into it.
2. If Chrome exposes its saved-credential chooser from that field, Select the **first saved credential** without reading any account names or values.
3. If the chooser is not exposed in the page accessibility tree, do **not** treat that as a missing credential or a login blocker. Use Chrome's current-site **Manage your passwords** toolbar control to open the saved-password picker, then select its first entry by position without inspecting the entries.
4. Allow Chrome to fill the form. Use Discord's normal login action only if the page does not advance automatically.
5. Confirm success only from non-sensitive UI state, such as the authenticated Discord interface or the **Fantasy EPL Advisor** DM becoming visible.

The toolbar picker is part of Chrome's supported saved-login flow. It is the required fallback when the normal Discord email field does not visibly show the chooser; it does not authorize reading, copying, or choosing among credential values.

Never:

* inspect, read, copy, reveal, export, log, persist, or separately store the saved username or password;
* manually type a username, email, phone number, password, token, session value, or other credential;
* inspect filled credential fields, Chrome password storage, cookies, local or session storage, developer tools, network authentication data, or profile files;
* create a new Chrome profile;
* use another person's Discord account;
* choose a different saved credential;
* change, reset, save, or update the password;
* repeatedly retry rejected credentials;
* bypass MFA, CAPTCHA, security warnings, account approval, or suspicious-login checks.

If the first saved credential is unavailable or rejected, or a user-only challenge remains, stop and report the exact blocker.

Keep all Discord verification in the Owner-controlled **Fantasy EPL Advisor** DM and follow the Fantasy-owned Shared Chrome lifecycle above.
