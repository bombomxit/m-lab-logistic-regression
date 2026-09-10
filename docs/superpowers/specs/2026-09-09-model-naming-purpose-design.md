# Model naming and purpose design

## Goal

Replace opaque model-version codes in the learner-facing UI with a meaningful model name and purpose, while preserving the code as a technical identifier.

## Scope

- Require a learner-provided model name and purpose when starting training.
- Store the name and purpose with the training job and resulting model version.
- Show the name first throughout Models and Predict; show the version code as secondary metadata.
- Let a learner rename existing models and add or correct their purpose from Models.
- Give existing unnamed models a deterministic temporary display name based on their source dataset and label until edited.

## Non-goals

- No LLM or automatic semantic interpretation of a dataset.
- No automatic naming beyond the temporary fallback for already-trained models.
- No change to training, active-model behavior, prediction logs, or ML algorithms.
- No model deletion, comparison, sharing, or categorisation.

## User flow

1. On the existing Train page, the learner enters a concise `Tên model` and `Model này dùng để làm gì?` before choosing label/features and starting training.
2. A completed model shows its name as the title, its purpose as learner-facing context, and `v...` as the small technical code.
3. The Predict dropdown lists `Tên model · v...`; selection is by the meaningful name and does not change the active model.
4. On Models, a learner can edit the name/purpose of an existing version without retraining it.
5. Legacy versions with no saved name show `<tên CSV> - dự đoán <label>` and a visible prompt to complete their details.

## Technical design

- Add nullable `model_name` and `purpose` fields to `training_jobs` and `model_versions` through idempotent SQLite migrations in `init_db()`.
- Extend the start-training POST contract with `model_name` and `purpose`; persist them in the job so the background task can copy them to the created model version.
- Validate at the server boundary: trimmed name from 3 to 80 characters and purpose from 10 to 240 characters. Preserve submitted input and show the existing error view on validation failure.
- Add a CSRF-protected POST endpoint that updates only a model version's name and purpose after the same validation.
- Build the legacy display fallback in the model view/query layer, never as a background write. The real stored fields remain blank until the learner edits them.
- In templates, use the model name as the primary heading. Use `version` only in secondary labels and selector disambiguation.
- Predict's native select option remains one text value for accessibility and cross-browser consistency: `<model name> · <version>`.

## Error handling and safety

- Name and purpose are rendered through Jinja auto-escaping.
- The edit endpoint targets a server-loaded model id, validates CSRF and does not update active-state fields.
- Missing model ids retain the existing 404 behavior.
- Database migrations only add nullable columns and retain all existing rows.

## Verification

- Training rejects blank, too-short and too-long names/purposes.
- A successfully trained model retains its name and purpose in Models, Predict and after a server restart.
- Predict lists names before technical codes and selecting another named model loads that model without activating it.
- Editing a model changes its display details but not its version code, metrics or active state.
- Legacy rows render a deterministic fallback and remain editable.
- Existing upload, train, predict, model selection and CSV preview tests continue to pass.

## Scope check

The change only augments identity metadata already associated with each training job and model version. It does not alter the dataset contents, model artifact, train/test split or prediction contract.
