# Fantasy Browser & Authentication Procedure

Use this document for browser work, authenticated web services, saved-login flows, and Discord smoke testing.

## Shared Chrome

At the start of browser work, create a task-owned tab:

`infra-opt workspace create --project fantasy --agent-id TASK_ID --purpose SAFE_PURPOSE`

When finished, close it:

`infra-opt workspace close --project fantasy --agent-id TASK_ID --tab-id TAB_ID`

If a workspace command fails, times out, or reports a stale or unavailable heartbeat:

* stop browser work;
* alert Infrastructure once with only the project, task ID, failed command, safe error code, and UTC timestamp;
* do not include URLs, page content, credentials, or browser history;
* do not repeatedly retry;
* do not reload the extension;
* do not restart Chrome;
* do not create an unmanaged tab;
* do not troubleshoot the allocator yourself.

Infrastructure owns allocator recovery, including verification and reconciliation, the smallest safe repair, and its own create/touch/close smoke test.

Wait for Infrastructure's conclusive response:

`Chrome allocator healthy — retry now`

or a concrete blocker and next action.

Retry the original command once only after Infrastructure reports healthy.

Duplicate reports for the same failure are one incident. Do not create repeated alerts unless a genuinely new blocker appears.

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

## Discord saved-password login

For Discord, use the general saved-login rules above plus this exact procedure:

1. When Discord shows its normal login form, click or focus only **Email or Phone Number**. Do not type into it.
2. Select the **first saved credential** shown by Chrome.
3. Use Discord's normal login action only if the page does not advance automatically.
4. Confirm success only from non-sensitive UI state, such as the authenticated Discord interface or the **Fantasy EPL Advisor** DM becoming visible.

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

Keep all Discord verification in the Owner-controlled **Fantasy EPL Advisor** DM and follow the task-owned Shared Chrome lifecycle above.
