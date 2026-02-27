# Claude Code Workflow Templates — Symphony AI Server

Copy and paste these prompts to start common tasks with Claude Code.

---

## 1. Code Review

```
Review the recent changes in the voice_receptionist/ directory.
Focus on:
- Security issues (exposed secrets, unvalidated input)
- Error handling gaps
- Consistency with the project coding standards in CLAUDE.md

Output a prioritised list of findings with file:line references.
```

---

## 2. Add a New Feature

```
I need to add [FEATURE DESCRIPTION].

Before writing any code:
1. Read the relevant existing files.
2. Explain your approach and which files will change.
3. Wait for my approval before making changes.

Once approved, implement the feature following the coding standards in CLAUDE.md.
After implementation, run the linter and fix any issues.
```

---

## 3. Debug a Failing Service

```
[SERVICE NAME] is failing with this error:
[PASTE ERROR / STACK TRACE]

1. Read the relevant source file(s).
2. Identify the likely cause.
3. Propose a fix and explain why it will work.
4. Wait for approval, then apply the fix.
5. Verify the fix by checking syntax / running the linter.
```

---

## 4. Deploy a Docker Service Update

```
Deploy an update to [SERVICE NAME].

Steps (use admin scope):
1. Run: git fetch && git status  — confirm branch is up to date.
2. Run: docker compose ps  — confirm current health.
3. Run: docker compose build --no-cache [service]
4. Run: docker compose up -d [service]
5. Run: docker compose ps  — confirm (healthy) status.
6. Tail logs for 30 seconds: docker compose logs -f [service]

Stop and report any error at any step.
```

---

## 5. Onboard a New Client Node

```
Onboard a new Symphony Concierge node for client: [CLIENT NAME]
Address: [ADDRESS]
Tailscale key: [KEY]

Steps:
1. Add the client to client_ai/client_registry.json.
2. Show me the provisioning command to run on the Mac Mini.
3. After I confirm provisioning is complete, run the knowledge builder with:
   - Client name: [CLIENT NAME]
   - D-Tools CSV: [PATH]
4. Show the ollama create command to load the new model.
```

---

## 6. Run a D-Tools Data Import

```
Import D-Tools data for [CLIENT NAME].
CSV file: [PATH TO CSV]

1. Read client_ai/client_knowledge_builder.py to understand the expected format.
2. Preview the first 5 rows of the CSV.
3. Validate the CSV columns match the expected schema.
4. Run the knowledge builder and show me the output.
5. Display the first 20 lines of the generated Modelfile.
```

---

## 7. Generate a Client Knowledge Model

```
Build and load a new Ollama knowledge model for [CLIENT NAME].

1. Run client_knowledge_builder.py with the appropriate arguments.
2. Show me the full generated Modelfile before loading it.
3. Wait for my approval.
4. Run: ollama create symphony-[client]:v[VERSION] -f [MODELFILE PATH]
5. Run: ollama list  — confirm the new model appears.
6. Update client_registry.json with the new model version and today's date.
```
